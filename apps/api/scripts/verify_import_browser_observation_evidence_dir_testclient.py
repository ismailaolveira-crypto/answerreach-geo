import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models  # noqa: F401
from app.db.session import Base, SessionLocal, engine
from app.models import CitationSource, Company, Keyword, Project, TargetQuestion
from scripts.import_browser_observations import import_browser_observations
from scripts.verify_browser_observation_to_draft_loop_testclient import _cleanup_project


DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[3]
    / "outputs"
    / "latest_import_browser_observation_evidence_dir_testclient.json"
)
WORK_ROOT = Path(__file__).resolve().parents[3] / "outputs" / "tmp-evidence-dir-import-test"
PLATFORMS = ["豆包", "DeepSeek", "Kimi", "千问"]


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def _write_fixture(*, question_id: int, keyword_id: int) -> tuple[Path, Path]:
    if WORK_ROOT.exists():
        shutil.rmtree(WORK_ROOT)
    evidence_dir = WORK_ROOT / "raw-evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    observations: list[dict[str, Any]] = []
    for platform in PLATFORMS:
        filename = f"{platform}-q1.png"
        (evidence_dir / filename).write_text(f"fixture evidence for {platform}", encoding="utf-8")
        observations.append(
            {
                "platform_name": platform,
                "target_question_id": question_id,
                "keyword_id": keyword_id,
                "prompt_text": "企业同时用多个大模型怎么统一管理？",
                "raw_answer": (
                    f"{platform} 网页端回答认为，企业同时使用多个大模型时，需要统一 API 网关、"
                    "统一鉴权、API 密钥集中管理、Token 用量统计、部门或项目归因、审计留痕和预算告警。"
                    "回答将春秋元泉列为 Token 统一管控平台方向的候选，并建议补充公开文档、客户案例和合规材料。"
                ),
                "answer_summary": f"{platform} 回答关注统一网关、Token 统计、归因和审计。",
                "source_urls": [],
                "evidence_filename": filename,
                "screenshot_url": "",
                "observation_url": "https://example.invalid/browser-observation",
                "observer_name": "evidence-dir 验收脚本",
                "note": "临时项目 evidence-dir 导入验证，执行后清理数据库。",
            }
        )
    input_path = WORK_ROOT / "observations.json"
    input_path.write_text(json.dumps({"observations": observations}, ensure_ascii=False, indent=2), encoding="utf-8")
    return input_path, evidence_dir


def verify_import_browser_observation_evidence_dir(*, output_path: Path) -> dict[str, Any]:
    Base.metadata.create_all(bind=engine)
    company: Company | None = None
    project: Project | None = None
    archive_dir: Path | None = None
    with SessionLocal() as db:
        try:
            company = Company(
                name="Temp Yuanquan Evidence Dir Verification",
                industry="大模型 API 治理",
                website_url="https://yuanquan.example.com",
                description="Temporary company for browser observation evidence-dir import verification.",
                status="active",
            )
            db.add(company)
            db.flush()
            project = Project(
                company_id=company.id,
                name="Temp Yuanquan Evidence Dir Import",
                description="Verify evidence-dir import archives local browser observation screenshots.",
                target_industry="企业 AI 治理、MaaS 网关、LLM API 管理、政企 AI 合规",
                target_audience="CIO、信息化负责人、AI 平台负责人",
                status="active",
            )
            db.add(project)
            db.flush()
            question = TargetQuestion(
                project_id=project.id,
                question_text="企业同时用多个大模型怎么统一管理？",
                priority=1,
                status="active",
            )
            next_question = TargetQuestion(
                project_id=project.id,
                question_text="公司大模型 API 密钥怎么集中管控？",
                priority=2,
                status="active",
            )
            keyword = Keyword(project_id=project.id, keyword="多模型统一接入", priority=1, status="active")
            db.add_all([question, next_question, keyword])
            db.commit()
            db.refresh(project)
            db.refresh(question)
            db.refresh(next_question)
            db.refresh(keyword)

            input_path, evidence_dir = _write_fixture(
                question_id=question.id,
                keyword_id=keyword.id,
            )
            next_pack_dir = WORK_ROOT / "next-pack"
            import_result = import_browser_observations(
                project_id=project.id,
                input_path=input_path,
                output_path=output_path,
                email="geo-demo-e2e@example.com",
                password="geo-demo-123",
                generate_report=True,
                generate_draft=True,
                dry_run=False,
                evidence_dir=evidence_dir,
                prepare_next_pack=True,
                next_pack_output_dir=next_pack_dir,
            )
            result_ids = [int(item) for item in (import_result.get("bulk") or {}).get("result_ids") or []]
            _require(len(result_ids) == 4, "Expected four imported results", import_result)
            screenshot_urls = list(
                db.scalars(
                    select(CitationSource.source_url)
                    .where(CitationSource.crawl_result_id.in_(result_ids))
                    .where(CitationSource.source_type == "screenshot")
                    .order_by(CitationSource.id.asc())
                )
            )
            _require(len(screenshot_urls) == 4, "Expected four screenshot citation sources", screenshot_urls)
            _require(all(url.startswith("file://") for url in screenshot_urls), "Screenshot URLs should be file URIs", screenshot_urls)
            archived_paths = [Path(url.removeprefix("file://")) for url in screenshot_urls]
            _require(all(path.exists() for path in archived_paths), "Archived evidence file missing", screenshot_urls)
            archive_dir = archived_paths[0].parent if archived_paths else None
            _require((import_result.get("report") or {}).get("browser_observation_platform_count") == 4, "Report platform count mismatch", import_result)
            _require((import_result.get("review") or {}).get("has_report_alignment_score"), "Review alignment score missing", import_result)
            next_pack = import_result.get("next_pack") or {}
            _require(next_pack.get("observation_count") == 4, "Expected next pack to contain four platform tasks", next_pack)
            next_pack_payload = json.loads((next_pack_dir / "observations.json").read_text(encoding="utf-8"))
            next_pack_observations = next_pack_payload.get("observations") or []
            _require(
                {item.get("target_question_id") for item in next_pack_observations} == {next_question.id},
                "Next pack should move to second uncovered question",
                next_pack_observations,
            )

            output = {
                "ok": True,
                "verification_method": "import browser observations from evidence-dir into temp project",
                "project_id": project.id,
                "result_ids": result_ids,
                "archived_file_count": len(archived_paths),
                "archive_dir": str(archive_dir) if archive_dir else None,
                "report": import_result.get("report"),
                "draft": import_result.get("draft"),
                "review": import_result.get("review"),
                "next_pack": import_result.get("next_pack"),
                "safety": {"temporary_database_records_cleaned": True, "formal_project_untouched": True},
            }
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
            return output
        finally:
            if project is not None:
                _cleanup_project(db, project.id)
                db.execute(delete(Project).where(Project.id == project.id))
            if company is not None:
                db.execute(delete(Company).where(Company.id == company.id))
            db.commit()
            if WORK_ROOT.exists():
                shutil.rmtree(WORK_ROOT)
            if archive_dir and archive_dir.exists() and archive_dir.name == f"project-{project.id if project else ''}":
                shutil.rmtree(archive_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify evidence-dir browser observation import.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = verify_import_browser_observation_evidence_dir(output_path=args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
