import argparse
import json
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models  # noqa: F401
from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.models import (
    AnswerAnalysis,
    AuditLog,
    CitationSource,
    Company,
    CrawlResult,
    CrawlTask,
    Keyword,
    LLMProvider,
    MaturityReport,
    MaturityScoreItem,
    MentionedEntity,
    Project,
    ProjectStageGoal,
    TargetQuestion,
    UsageRecord,
)


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_real_provider_diagnostic_flow_testclient.json"


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def verify_real_provider_diagnostic_flow(
    *,
    output_path: Path,
    email: str = "geo-demo-e2e@example.com",
    password: str = "geo-demo-123",
) -> dict[str, Any]:
    Base.metadata.create_all(bind=engine)
    company: Company | None = None
    project: Project | None = None
    provider: LLMProvider | None = None
    created_goal_ids: list[int] = []
    report_id: int | None = None
    task_id: int | None = None

    with SessionLocal() as db:
        try:
            company = Company(
                name="Temp Real Diagnostic Verification",
                industry="GEO 实采",
                description="Temporary company for real-provider diagnostic flow verification.",
                status="active",
            )
            db.add(company)
            db.flush()
            project = Project(
                company_id=company.id,
                name="Temp Real Diagnostic Project",
                target_industry="GEO SaaS",
                target_audience="市场负责人",
                status="active",
            )
            db.add(project)
            db.flush()
            question = TargetQuestion(
                project_id=project.id,
                question_text="企业要怎么验证 GEO 服务商是否真的有效？",
                question_type="core",
                priority=5,
                status="active",
            )
            keyword = Keyword(
                project_id=project.id,
                keyword="GEO 服务商验证",
                keyword_type="core",
                priority=5,
                status="active",
            )
            provider = LLMProvider(
                name="Temp Real Diagnostic Preflight Provider",
                provider_type="openai_compatible",
                model_name="mock-real-diagnostic",
                auth_config={"api_key_configured": True, "api_key_redacted": True},
                status="active",
            )
            db.add_all([question, keyword, provider])
            db.commit()

            client = TestClient(app)
            login = client.post("/api/auth/login", json={"email": email, "password": password})
            login.raise_for_status()
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            response = client.post(
                f"/api/projects/{project.id}/diagnostic-runs",
                headers=headers,
                json={
                    "provider_ids": [provider.id],
                    "target_question_ids": [question.id],
                    "keyword_ids": [],
                    "execute_now": True,
                    "generate_report": True,
                    "create_action_goals": True,
                    "title": "真实模型小样本诊断 - 临时项目",
                    "report_period": "real_provider_smoke",
                },
            )
            response.raise_for_status()
            payload = response.json()
            report_id = payload.get("report_id")
            task_id = payload.get("task_id")
            task_id = payload.get("task_id")
            _require(payload["task_status"] == "failed", "Untested real provider should be blocked", payload)
            _require(payload["expected_call_count"] == 1, "Real diagnostic should still estimate one prompt", payload)
            _require(payload["result_count"] == 0, "Blocked real diagnostic should not create results", payload)
            _require(report_id is None, "Blocked real diagnostic should not create report", payload)
            blockers = payload.get("blockers") or []
            blocker_text = "；".join(str(blocker) for blocker in blockers)
            _require("Provider preflight failed" in blocker_text, "Preflight failure message missing", payload)
            _require("OPENAI_API_KEY" in blocker_text, "Missing key should be named in blocker", payload)
            created_goals = []

            result = {
                "ok": True,
                "verification_method": "FastAPI TestClient real-provider diagnostic entry and preflight contract",
                "project_id": project.id,
                "provider_id": provider.id,
                "task_id": task_id,
                "task_status": payload["task_status"],
                "blockers": blockers,
                "expected_call_count": payload["expected_call_count"],
                "result_count": payload["result_count"],
                "report_id": None,
                "action_goal_count": len(created_goals),
                "safety": {
                    "real_external_calls": 0,
                    "blocked_without_real_api_key": True,
                    "temporary_data_cleaned": True,
                },
            }
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        finally:
            if project is not None:
                result_ids = list(db.scalars(select(CrawlResult.id).where(CrawlResult.project_id == project.id)))
                task_ids = list(db.scalars(select(CrawlTask.id).where(CrawlTask.project_id == project.id)))
                report_ids = list(db.scalars(select(MaturityReport.id).where(MaturityReport.project_id == project.id)))
                if created_goal_ids:
                    db.execute(delete(ProjectStageGoal).where(ProjectStageGoal.id.in_(created_goal_ids)))
                if report_ids:
                    db.execute(delete(MaturityScoreItem).where(MaturityScoreItem.report_id.in_(report_ids)))
                    db.execute(delete(MaturityReport).where(MaturityReport.id.in_(report_ids)))
                if result_ids:
                    db.execute(delete(UsageRecord).where(UsageRecord.crawl_result_id.in_(result_ids)))
                    db.execute(delete(AnswerAnalysis).where(AnswerAnalysis.crawl_result_id.in_(result_ids)))
                    db.execute(delete(MentionedEntity).where(MentionedEntity.crawl_result_id.in_(result_ids)))
                    db.execute(delete(CitationSource).where(CitationSource.crawl_result_id.in_(result_ids)))
                    db.execute(delete(CrawlResult).where(CrawlResult.id.in_(result_ids)))
                if task_ids:
                    db.execute(delete(UsageRecord).where(UsageRecord.task_id.in_(task_ids)))
                    db.execute(delete(CrawlTask).where(CrawlTask.id.in_(task_ids)))
                db.execute(delete(AuditLog).where(AuditLog.project_id == project.id))
                db.execute(delete(Keyword).where(Keyword.project_id == project.id))
                db.execute(delete(TargetQuestion).where(TargetQuestion.project_id == project.id))
                db.execute(delete(Project).where(Project.id == project.id))
            if provider is not None:
                db.execute(delete(LLMProvider).where(LLMProvider.id == provider.id))
            if company is not None:
                db.execute(delete(Company).where(Company.id == company.id))
            db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify real-provider diagnostic entry and preflight contract.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--email", default="geo-demo-e2e@example.com")
    parser.add_argument("--password", default="geo-demo-123")
    args = parser.parse_args()
    result = verify_real_provider_diagnostic_flow(output_path=args.output, email=args.email, password=args.password)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
