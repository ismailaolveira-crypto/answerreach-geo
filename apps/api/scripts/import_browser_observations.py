import argparse
import json
import shutil
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models  # noqa: F401
from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.models import LLMProvider, Project
from app.schemas.content import ArticleDraftGenerate
from app.schemas.report import MaturityReportCreate
from app.services.article_workflow import generate_article_draft, review_article_draft
from app.services.maturity_report import generate_maturity_report
from scripts.prepare_browser_observation_collection_pack import DEFAULT_OUTPUT_DIR as DEFAULT_NEXT_PACK_OUTPUT_DIR
from scripts.prepare_browser_observation_collection_pack import prepare_collection_pack


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_import_browser_observations.json"
DEFAULT_EVIDENCE_ROOT = Path(__file__).resolve().parents[3] / "outputs" / "browser-observation-evidence"
REQUIRED_PLATFORMS = {"豆包", "DeepSeek", "Kimi", "千问"}
PLACEHOLDER_PATTERNS = [
    "粘贴该平台网页端返回的完整答案",
    "粘贴网页端大模型返回的完整答案",
    "可选：一句话摘要",
    "https://example.com",
    "example.com",
    "/path/to/screenshot",
    "待填",
    "TODO",
]
EVIDENCE_FILENAME_KEYS = ("evidence_filename", "screenshot_filename", "evidence_file", "screenshot_file")
LOCAL_EVIDENCE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".mov", ".mp4", ".pdf", ".png", ".webp"}


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def _read_observations(input_path: Path) -> list[dict[str, Any]]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    observations = payload.get("observations") if isinstance(payload, dict) else payload
    _require(isinstance(observations, list), "Input must be a JSON array or an object with observations")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(observations, start=1):
        _require(isinstance(item, dict), f"Observation #{index} must be an object", item)
        normalized.append(item)
    return normalized


def _as_string(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    return value.strip() if isinstance(value, str) else ""


def _as_optional_int(record: dict[str, Any], key: str) -> int | None:
    value = record.get(key)
    number = value if isinstance(value, int) else int(value) if str(value or "").isdigit() else None
    return number if number and number > 0 else None


def _as_string_list(record: dict[str, Any], key: str) -> list[str]:
    value = record.get(key)
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.splitlines() if item.strip()]
    return []


def _contains_placeholder(value: Any) -> bool:
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value or "")
    return any(pattern in text for pattern in PLACEHOLDER_PATTERNS)


def _safe_filename(value: str) -> str:
    normalized = "".join(char if char.isalnum() or char in {".", "-", "_"} else "-" for char in value.strip())
    while "--" in normalized:
        normalized = normalized.replace("--", "-")
    return normalized.strip("-")[:120] or "evidence"


def _file_uri(path: Path) -> str:
    return f"file://{path.expanduser().resolve()}"


def _local_path_from_value(value: str, *, input_path: Path, evidence_dir: Path | None) -> Path | None:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        return None
    if parsed.scheme == "file":
        return Path(unquote(parsed.path)).expanduser()
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate
    search_roots = [root for root in [evidence_dir, input_path.parent] if root is not None]
    for root in search_roots:
        resolved = (root / candidate).expanduser()
        if resolved.exists():
            return resolved
    return (search_roots[0] / candidate).expanduser() if search_roots else candidate


def _archive_evidence_file(*, project_id: int, source_path: Path, platform_name: str, index: int) -> str:
    _require(source_path.exists(), f"Observation #{index} evidence file does not exist", str(source_path))
    _require(source_path.is_file(), f"Observation #{index} evidence path is not a file", str(source_path))
    _require(
        source_path.suffix.lower() in LOCAL_EVIDENCE_EXTENSIONS,
        f"Observation #{index} evidence file type is unsupported",
        str(source_path),
    )
    target_dir = DEFAULT_EVIDENCE_ROOT / f"project-{project_id}"
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_platform = _safe_filename(platform_name)
    target_name = f"{index:02d}-{safe_platform}-{_safe_filename(source_path.name)}"
    target_path = target_dir / target_name
    if source_path.resolve() != target_path.resolve():
        shutil.copy2(source_path, target_path)
    return _file_uri(target_path)


def _resolve_screenshot_url(
    *,
    record: dict[str, Any],
    input_path: Path,
    evidence_dir: Path | None,
    project_id: int,
    platform_name: str,
    index: int,
    archive_evidence: bool,
) -> str:
    screenshot_url = _as_string(record, "screenshot_url")
    if _contains_placeholder(screenshot_url):
        screenshot_url = ""
    evidence_filename = next((_as_string(record, key) for key in EVIDENCE_FILENAME_KEYS if _as_string(record, key)), "")
    evidence_value = evidence_filename or screenshot_url
    local_path = _local_path_from_value(evidence_value, input_path=input_path, evidence_dir=evidence_dir)
    if local_path and (evidence_filename or local_path.exists()):
        if archive_evidence:
            return _archive_evidence_file(
                project_id=project_id,
                source_path=local_path,
                platform_name=platform_name,
                index=index,
            )
        _require(local_path.exists(), f"Observation #{index} evidence file does not exist", str(local_path))
        return _file_uri(local_path)
    return screenshot_url


def _provider_by_platform(db, project_id: int) -> dict[str, int]:
    project = db.get(Project, project_id)
    _require(project is not None, "Project not found", project_id)
    providers = list(
        db.scalars(
            select(LLMProvider)
            .where(LLMProvider.provider_type == "browser_observation")
            .where(LLMProvider.status == "active")
            .order_by(LLMProvider.id.asc())
        )
    )
    mapping = {
        str(provider.cost_rule.get("platform_name") or provider.name): provider.id
        for provider in providers
    }
    missing = REQUIRED_PLATFORMS - set(mapping)
    _require(not missing, "Missing active browser observation providers", sorted(missing))
    return mapping


def _normalize_observations(
    raw_observations: list[dict[str, Any]],
    provider_mapping: dict[str, int],
    *,
    project_id: int,
    input_path: Path,
    evidence_dir: Path | None,
    archive_evidence: bool,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for index, record in enumerate(raw_observations, start=1):
        platform_name = _as_string(record, "platform_name")
        prompt_text = _as_string(record, "prompt_text")
        raw_answer = _as_string(record, "raw_answer")
        _require(platform_name in REQUIRED_PLATFORMS, f"Observation #{index} platform unsupported", platform_name)
        _require(prompt_text, f"Observation #{index} prompt_text is required")
        screenshot_url = _resolve_screenshot_url(
            record=record,
            input_path=input_path,
            evidence_dir=evidence_dir,
            project_id=project_id,
            platform_name=platform_name,
            index=index,
            archive_evidence=archive_evidence,
        )
        record_for_validation = {**record, "screenshot_url": screenshot_url}
        for key in EVIDENCE_FILENAME_KEYS:
            record_for_validation.pop(key, None)
        _require(not _contains_placeholder(record_for_validation), f"Observation #{index} still contains placeholder text", record)
        _require(len(raw_answer) >= 80, f"Observation #{index} raw_answer is too short")
        _require(screenshot_url, f"Observation #{index} screenshot_url is required")
        observations.append(
            {
                "provider_id": _as_optional_int(record, "provider_id") or provider_mapping[platform_name],
                "report_id": _as_optional_int(record, "report_id"),
                "target_question_id": _as_optional_int(record, "target_question_id"),
                "keyword_id": _as_optional_int(record, "keyword_id"),
                "platform_name": platform_name,
                "prompt_text": prompt_text,
                "raw_answer": raw_answer,
                "answer_summary": _as_string(record, "answer_summary") or None,
                "source_urls": _as_string_list(record, "source_urls"),
                "screenshot_url": screenshot_url,
                "observation_url": _as_string(record, "observation_url") or None,
                "observer_name": _as_string(record, "observer_name") or "外部网页端采集",
                "note": _as_string(record, "note") or "外部浏览器网页端人工观测，含截图留证。",
            }
        )
    return observations


def import_browser_observations(
    *,
    project_id: int,
    input_path: Path,
    output_path: Path,
    email: str,
    password: str,
    generate_report: bool,
    generate_draft: bool,
    dry_run: bool,
    evidence_dir: Path | None,
    prepare_next_pack: bool = False,
    next_pack_output_dir: Path | None = None,
) -> dict[str, Any]:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        provider_mapping = _provider_by_platform(db, project_id)
    observations = _normalize_observations(
        _read_observations(input_path),
        provider_mapping,
        project_id=project_id,
        input_path=input_path,
        evidence_dir=evidence_dir,
        archive_evidence=not dry_run,
    )
    platform_names = {item["platform_name"] for item in observations}
    _require(
        REQUIRED_PLATFORMS.issubset(platform_names),
        "Input should include at least one observation for each required platform",
        sorted(REQUIRED_PLATFORMS - platform_names),
    )

    if dry_run:
        result = {
            "ok": True,
            "dry_run": True,
            "project_id": project_id,
            "input": str(input_path),
            "observation_count": len(observations),
            "platforms": sorted(platform_names),
            "evidence_dir": str(evidence_dir) if evidence_dir else None,
            "generate_report": generate_report,
            "generate_draft": generate_draft,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    client = TestClient(app)
    login = client.post("/api/auth/login", json={"email": email, "password": password})
    login.raise_for_status()
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    response = client.post(
        f"/api/projects/{project_id}/browser-observations/bulk",
        headers=headers,
        json={"observations": observations},
    )
    response.raise_for_status()
    bulk_detail = response.json()
    report_detail: dict[str, Any] | None = None
    draft_detail: dict[str, Any] | None = None
    review_detail: dict[str, Any] | None = None
    next_pack_detail: dict[str, Any] | None = None

    if generate_report or generate_draft:
        with SessionLocal() as db:
            project = db.get(Project, project_id)
            _require(project is not None, "Project not found after import", project_id)
            report = generate_maturity_report(
                db,
                project,
                MaturityReportCreate(title="网页端四平台真实观测后 GEO 成熟度报告"),
            )
            evidence_quality = report.report_json.get("evidence_quality") or {}
            report_detail = {
                "id": report.id,
                "title": report.title,
                "total_score": report.total_score,
                "maturity_level": report.maturity_level,
                "browser_observation_count": evidence_quality.get("browser_observation_count"),
                "browser_observation_platform_count": evidence_quality.get("browser_observation_platform_count"),
                "screenshot_evidence_count": evidence_quality.get("screenshot_evidence_count"),
            }
            if generate_draft:
                topic = observations[0]["prompt_text"]
                draft = generate_article_draft(
                    db,
                    project,
                    ArticleDraftGenerate(
                        topic=topic,
                        source_context={
                            "source_type": "maturity_report",
                            "source_report_id": report.id,
                            "source_report_title": report.title,
                            "topic_source": "external_browser_observation_import",
                            "browser_observation_result_ids": bulk_detail.get("result_ids") or [],
                            "browser_observation_platforms": sorted(platform_names),
                            "report_detail_action": "external_browser_observation_import_generate_report_draft",
                        },
                    ),
                )
                review = review_article_draft(db, draft, review_type="ai")
                draft_detail = {"id": draft.id, "title": draft.title, "status": draft.status}
                review_detail = {
                    "id": review.id,
                    "total_score": review.total_score,
                    "grade": review.grade,
                    "has_report_alignment_score": "报告承接度" in (review.dimension_scores or {}),
                }

    if prepare_next_pack:
        next_pack_detail = prepare_collection_pack(
            project_id=project_id,
            output_dir=next_pack_output_dir or DEFAULT_NEXT_PACK_OUTPUT_DIR,
            question_limit=1,
            keyword_limit=0,
            platforms=sorted(REQUIRED_PLATFORMS),
        )

    result = {
        "ok": True,
        "dry_run": False,
        "project_id": project_id,
        "input": str(input_path),
        "bulk": {
            "created_count": bulk_detail.get("created_count"),
            "result_ids": bulk_detail.get("result_ids"),
            "source_count": bulk_detail.get("source_count"),
            "screenshot_evidence_count": bulk_detail.get("screenshot_evidence_count"),
        },
        "platforms": sorted(platform_names),
        "evidence_archive": str(DEFAULT_EVIDENCE_ROOT / f"project-{project_id}"),
        "report": report_detail,
        "draft": draft_detail,
        "review": review_detail,
        "next_pack": next_pack_detail,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import externally collected browser observations and optionally generate report/draft/review."
    )
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--email", default="geo-demo-e2e@example.com")
    parser.add_argument("--password", default="geo-demo-123")
    parser.add_argument("--generate-report", action="store_true")
    parser.add_argument("--generate-draft", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--prepare-next-pack", action="store_true")
    parser.add_argument("--next-pack-output-dir", type=Path, default=DEFAULT_NEXT_PACK_OUTPUT_DIR)
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        help="Optional directory containing screenshot/video files referenced by evidence_filename or screenshot_filename.",
    )
    args = parser.parse_args()
    result = import_browser_observations(
        project_id=args.project_id,
        input_path=args.input,
        output_path=args.output,
        email=args.email,
        password=args.password,
        generate_report=args.generate_report or args.generate_draft,
        generate_draft=args.generate_draft,
        dry_run=args.dry_run,
        evidence_dir=args.evidence_dir,
        prepare_next_pack=args.prepare_next_pack,
        next_pack_output_dir=args.next_pack_output_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
