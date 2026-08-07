import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import models  # noqa: F401
from app.db.session import Base, SessionLocal, engine
from app.models import AnswerAnalysis, Company, CrawlResult, CrawlTask, LLMProvider, Project, TargetQuestion
from export_browser_observation_template import export_browser_observation_template
from scripts.verify_browser_observation_to_draft_loop_testclient import _cleanup_project


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_browser_observation_pack_gap_selection.json"
WORK_ROOT = Path(__file__).resolve().parents[3] / "outputs" / "tmp-browser-observation-pack-gap-selection"
PLATFORMS = [
    ("豆包", "https://www.doubao.com/chat/"),
    ("DeepSeek", "https://chat.deepseek.com/"),
    ("Kimi", "https://www.kimi.com/"),
    ("千问", "https://www.qianwen.com/"),
]


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def _provider_platform(provider: LLMProvider) -> str:
    return str((provider.cost_rule or {}).get("platform_name") or provider.name).strip()


def _ensure_browser_providers(db) -> list[int]:
    created_ids: list[int] = []
    providers = list(
        db.scalars(
            select(LLMProvider)
            .where(LLMProvider.provider_type == "browser_observation")
            .where(LLMProvider.status == "active")
        )
    )
    existing = {_provider_platform(provider): provider for provider in providers}
    for platform, url in PLATFORMS:
        if platform in existing:
            continue
        provider = LLMProvider(
            name=f"Temp {platform} browser observation",
            provider_type="browser_observation",
            api_base_url=url,
            model_name="web-ui-observation",
            auth_config={"mode": "manual"},
            cost_rule={"platform_name": platform},
            status="active",
        )
        db.add(provider)
        db.flush()
        created_ids.append(provider.id)
    return created_ids


def _seed_browser_coverage(
    db,
    *,
    project: Project,
    question: TargetQuestion,
    platforms: list[tuple[str, str]] | None = None,
) -> list[int]:
    result_ids: list[int] = []
    for platform, _url in platforms or PLATFORMS:
        task = CrawlTask(
            project_id=project.id,
            task_type="browser_observation_manual",
            schedule_type="manual",
            provider_ids=[],
            target_question_ids=[question.id],
            keyword_ids=[],
            status="success",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
        db.add(task)
        db.flush()
        result = CrawlResult(
            task_id=task.id,
            project_id=project.id,
            target_question_id=question.id,
            keyword_id=None,
            provider_id=None,
            prompt_text=question.question_text,
            raw_answer=f"{platform} 临时覆盖样本：第一题已经完成网页端观测。",
            answer_summary=f"{platform} 第一题已覆盖。",
            status="success",
            collected_at=datetime.now(UTC),
        )
        db.add(result)
        db.flush()
        db.add(
            AnswerAnalysis(
                crawl_result_id=result.id,
                company_mentioned=False,
                company_recommended=False,
                sentiment="neutral",
                confidence=80,
                analysis_json={
                    "method": "browser_observation_manual",
                    "browser_observation": {
                        "platform_name": platform,
                        "observer_name": "gap selection verification",
                    },
                },
            )
        )
        result_ids.append(result.id)
    return result_ids


def verify_pack_gap_selection(*, output_path: Path) -> dict[str, Any]:
    Base.metadata.create_all(bind=engine)
    company: Company | None = None
    project: Project | None = None
    created_provider_ids: list[int] = []
    if WORK_ROOT.exists():
        shutil.rmtree(WORK_ROOT)
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    template_path = WORK_ROOT / "observations.json"
    with SessionLocal() as db:
        try:
            created_provider_ids = _ensure_browser_providers(db)
            company = Company(
                name="Temp Yuanquan Pack Gap Verification",
                industry="大模型 API 治理",
                website_url="https://yuanquan.example.com",
                description="Temporary company for browser observation pack gap selection verification.",
                status="active",
            )
            db.add(company)
            db.flush()
            project = Project(
                company_id=company.id,
                name="Temp Yuanquan Pack Gap Selection",
                description="Verify pack generation skips covered question/platform pairs.",
                target_industry="企业 AI 治理",
                target_audience="AI 平台负责人",
                status="active",
            )
            db.add(project)
            db.flush()
            question_1 = TargetQuestion(
                project_id=project.id,
                question_text="企业同时用多个大模型怎么统一管理？",
                priority=1,
                status="active",
            )
            question_2 = TargetQuestion(
                project_id=project.id,
                question_text="公司大模型 API 密钥怎么集中管控？",
                priority=2,
                status="active",
            )
            db.add_all([question_1, question_2])
            db.commit()
            db.refresh(project)
            db.refresh(question_1)
            db.refresh(question_2)

            partial_covered_result_ids = _seed_browser_coverage(db, project=project, question=question_1, platforms=PLATFORMS[:1])
            db.commit()

            export_result = export_browser_observation_template(
                project_id=project.id,
                output_path=template_path,
                question_limit=1,
                keyword_limit=0,
                platforms=[platform for platform, _url in PLATFORMS],
            )
            payload = json.loads(template_path.read_text(encoding="utf-8"))
            observations = payload.get("observations") or []
            target_ids = {item.get("target_question_id") for item in observations}
            platforms_after_partial = {item.get("platform_name") for item in observations}
            evidence_filenames = [item.get("evidence_filename") for item in observations]

            _require(len(observations) == 3, "Expected three missing platform observations after one platform is covered", observations)
            _require(target_ids == {question_1.id}, "Pack should stay on first question until all platforms are covered", target_ids)
            _require(
                platforms_after_partial == {platform for platform, _url in PLATFORMS[1:]},
                "Pack should only contain the remaining first-question platforms",
                platforms_after_partial,
            )
            _require(
                (payload.get("coverage") or {}).get("existing_browser_observation_pairs") == 1,
                "Coverage metadata should count the seeded single-platform pair",
                payload.get("coverage"),
            )

            remaining_covered_result_ids = _seed_browser_coverage(
                db,
                project=project,
                question=question_1,
                platforms=PLATFORMS[1:],
            )
            db.commit()

            export_result = export_browser_observation_template(
                project_id=project.id,
                output_path=template_path,
                question_limit=1,
                keyword_limit=0,
                platforms=[platform for platform, _url in PLATFORMS],
            )
            payload = json.loads(template_path.read_text(encoding="utf-8"))
            observations = payload.get("observations") or []
            target_ids = {item.get("target_question_id") for item in observations}
            evidence_filenames = [item.get("evidence_filename") for item in observations]

            _require(len(observations) == 4, "Expected four missing platform observations for next question", observations)
            _require(target_ids == {question_2.id}, "Pack should skip fully covered first question", target_ids)
            _require(
                all(str(filename).endswith(f"question-{question_2.id}.png") for filename in evidence_filenames),
                "Evidence filenames should point to second question",
                evidence_filenames,
            )
            _require(
                (payload.get("coverage") or {}).get("existing_browser_observation_pairs") == 4,
                "Coverage metadata should count the seeded first-question pairs",
                payload.get("coverage"),
            )

            output = {
                "ok": True,
                "verification_method": "temporary project pack generation skips covered question-platform pairs",
                "project_id": project.id,
                "covered_question_id": question_1.id,
                "next_question_id": question_2.id,
                "partial_covered_result_ids": partial_covered_result_ids,
                "remaining_covered_result_ids": remaining_covered_result_ids,
                "export_result": export_result,
                "observation_count": len(observations),
                "evidence_filenames": evidence_filenames,
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
            if created_provider_ids:
                db.execute(delete(LLMProvider).where(LLMProvider.id.in_(created_provider_ids)))
            db.commit()
            if WORK_ROOT.exists():
                shutil.rmtree(WORK_ROOT)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify browser observation pack gap selection.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = verify_pack_gap_selection(output_path=args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
