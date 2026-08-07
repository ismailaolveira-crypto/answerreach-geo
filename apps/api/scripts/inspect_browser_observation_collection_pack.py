import argparse
import json
import sys
from pathlib import Path
from typing import Any


DEFAULT_PACK_DIR = Path(__file__).resolve().parents[3] / "outputs" / "yuanquan_browser_observation_pack_q1"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_browser_observation_pack_status.json"
REQUIRED_PLATFORMS = ["豆包", "DeepSeek", "Kimi", "千问"]
PLACEHOLDER_PATTERNS = [
    "粘贴该平台网页端返回的完整答案",
    "粘贴网页端大模型返回的完整答案",
    "待填",
    "TODO",
    "如不使用 --evidence-dir",
    "/path/to/screenshot",
]


def _read_observations(input_path: Path) -> list[dict[str, Any]]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    observations = payload.get("observations") if isinstance(payload, dict) else payload
    if not isinstance(observations, list):
        raise AssertionError("observations.json must be a JSON array or an object with observations.")
    return [item for item in observations if isinstance(item, dict)]


def _as_string(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    return value.strip() if isinstance(value, str) else ""


def _contains_placeholder(value: Any) -> bool:
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value or "")
    return any(pattern in text for pattern in PLACEHOLDER_PATTERNS)


def _source_urls(record: dict[str, Any]) -> list[str]:
    value = record.get("source_urls")
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.splitlines() if item.strip()]
    return []


def _evidence_status(record: dict[str, Any], evidence_dir: Path) -> dict[str, Any]:
    evidence_filename = _as_string(record, "evidence_filename")
    screenshot_url = _as_string(record, "screenshot_url")
    evidence_path = evidence_dir / evidence_filename if evidence_filename else None
    file_exists = bool(evidence_path and evidence_path.exists() and evidence_path.is_file())
    external_url_ready = bool(screenshot_url and not _contains_placeholder(screenshot_url))
    return {
        "evidence_filename": evidence_filename or None,
        "evidence_path": str(evidence_path) if evidence_path else None,
        "file_exists": file_exists,
        "screenshot_url": screenshot_url or None,
        "external_url_ready": external_url_ready,
        "ready": file_exists or external_url_ready,
    }


def inspect_collection_pack(
    *,
    pack_dir: Path,
    input_path: Path | None,
    evidence_dir: Path | None,
    output_path: Path,
) -> dict[str, Any]:
    resolved_input = input_path or pack_dir / "observations.json"
    resolved_evidence_dir = evidence_dir or pack_dir / "raw-evidence"
    observations = _read_observations(resolved_input)
    platform_items: list[dict[str, Any]] = []
    blocking_issue_count = 0
    warning_count = 0
    for index, record in enumerate(observations, start=1):
        platform_name = _as_string(record, "platform_name")
        prompt_text = _as_string(record, "prompt_text")
        raw_answer = _as_string(record, "raw_answer")
        answer_summary = _as_string(record, "answer_summary")
        sources = _source_urls(record)
        evidence = _evidence_status(record, resolved_evidence_dir)
        issues: list[str] = []
        warnings: list[str] = []
        if platform_name not in REQUIRED_PLATFORMS:
            issues.append("平台不在首批四平台范围内")
        if not prompt_text:
            issues.append("缺少 prompt_text")
        if not raw_answer or _contains_placeholder(raw_answer):
            issues.append("raw_answer 仍是空值或占位文本")
        elif len(raw_answer) < 80:
            issues.append("raw_answer 少于 80 个字符")
        if answer_summary and _contains_placeholder(answer_summary):
            warnings.append("answer_summary 仍是占位文本")
        if not evidence["ready"]:
            issues.append("缺少截图/录屏证据文件或可用 screenshot_url")
        if not sources:
            warnings.append("未填写页面可见信源 URL；如果网页端没有展示信源可以保留为空")
        blocking_issue_count += len(issues)
        warning_count += len(warnings)
        platform_items.append(
            {
                "index": index,
                "platform_name": platform_name,
                "prompt_text": prompt_text,
                "raw_answer_length": len(raw_answer),
                "answer_ready": bool(raw_answer and not _contains_placeholder(raw_answer) and len(raw_answer) >= 80),
                "evidence": evidence,
                "source_count": len(sources),
                "issues": issues,
                "warnings": warnings,
                "ready": not issues,
            }
        )
    covered_platforms = sorted({item["platform_name"] for item in platform_items if item["platform_name"]})
    missing_platforms = [platform for platform in REQUIRED_PLATFORMS if platform not in covered_platforms]
    ready_platforms = sorted({item["platform_name"] for item in platform_items if item["ready"]})
    result = {
        "ok": True,
        "ready": blocking_issue_count == 0 and not missing_platforms and len(observations) >= len(REQUIRED_PLATFORMS),
        "pack_dir": str(pack_dir),
        "input": str(resolved_input),
        "evidence_dir": str(resolved_evidence_dir),
        "observation_count": len(observations),
        "required_platforms": REQUIRED_PLATFORMS,
        "covered_platforms": covered_platforms,
        "ready_platforms": ready_platforms,
        "missing_platforms": missing_platforms,
        "blocking_issue_count": blocking_issue_count + len(missing_platforms),
        "warning_count": warning_count,
        "items": platform_items,
        "next_action": (
            "可运行 dry-run，随后正式导入并生成报告/稿件。"
            if blocking_issue_count == 0 and not missing_platforms
            else "继续补齐 raw_answer 和 raw-evidence 里的截图/录屏文件。"
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect browser observation collection pack readiness.")
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK_DIR)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    result = inspect_collection_pack(
        pack_dir=args.pack_dir,
        input_path=args.input,
        evidence_dir=args.evidence_dir,
        output_path=args.output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.require_ready and not result["ready"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
