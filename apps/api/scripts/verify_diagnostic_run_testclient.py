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
    Competitor,
    CrawlResult,
    CrawlTask,
    CrawlTaskLog,
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


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_diagnostic_run_testclient.json"


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def verify_diagnostic_run(
    *,
    output_path: Path,
    email: str = "geo-demo-e2e@example.com",
    password: str = "geo-demo-123",
) -> dict[str, Any]:
    Base.metadata.create_all(bind=engine)
    company: Company | None = None
    project: Project | None = None
    provider_ids: list[int] = []
    task_id: int | None = None
    report_id: int | None = None
    created_goal_ids: list[int] = []

    with SessionLocal() as db:
        try:
            company = Company(
                name="Temp Diagnostic Run Verification",
                industry="GEO 优化服务",
                website_url="https://example.com",
                description="Temporary company for diagnostic run verification.",
                brand_aliases=["诊断验证企业"],
                status="active",
            )
            db.add(company)
            db.flush()
            project = Project(
                company_id=company.id,
                name="Temp Diagnostic Run Project",
                description="Temporary project for one-click diagnostic run verification.",
                target_industry="GEO 优化",
                target_audience="市场与品牌负责人",
                status="active",
            )
            db.add(project)
            db.flush()
            providers = [
                LLMProvider(
                    name=f"Temp Diagnostic Mock Provider {index}",
                    provider_type="mock",
                    model_name=f"mock-geo-search-{index}",
                    auth_config={},
                    status="active",
                )
                for index in range(1, 4)
            ]
            db.add_all(providers)
            db.flush()
            provider_ids = [provider.id for provider in providers]
            questions = [
                TargetQuestion(
                    project_id=project.id,
                    question_text=f"GEO 优化服务目标问题 {index} 应该如何选择供应商？",
                    question_type="core",
                    priority=index,
                    status="active",
                )
                for index in range(1, 11)
            ]
            keywords = [
                Keyword(
                    project_id=project.id,
                    keyword=f"GEO 优化关键词 {index}",
                    keyword_type="core",
                    priority=index,
                    status="active",
                )
                for index in range(1, 11)
            ]
            competitors = [
                Competitor(project_id=project.id, name=f"诊断竞品 {index}", status="active")
                for index in range(1, 4)
            ]
            db.add_all([*questions, *keywords, *competitors])
            db.commit()

            client = TestClient(app)
            login = client.post("/api/auth/login", json={"email": email, "password": password})
            login.raise_for_status()
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            response = client.post(
                f"/api/projects/{project.id}/diagnostic-runs",
                headers=headers,
                json={
                    "provider_ids": provider_ids,
                    "execute_now": True,
                    "generate_report": True,
                    "create_action_goals": True,
                    "title": "Temp 一键 GEO 成熟度诊断报告",
                    "report_period": "verification",
                },
            )
            response.raise_for_status()
            payload = response.json()
            task_id = int(payload["task_id"])
            report_id = int(payload["report_id"])
            expected_call_count = (10 + 10 * 3) * 3
            _require(payload["task_status"] == "success", "Diagnostic crawl task did not finish successfully", payload)
            _require(payload["provider_count"] == 3, "Diagnostic run should cover three providers", payload)
            _require(payload["target_question_count"] == 10, "Diagnostic run should cover ten target questions", payload)
            _require(payload["keyword_count"] == 10, "Diagnostic run should cover ten keywords", payload)
            _require(payload["prompt_count"] == 40, "Diagnostic run prompt count mismatch", payload)
            _require(payload["expected_call_count"] == expected_call_count, "Diagnostic run call count mismatch", payload)
            _require(payload["result_count"] == expected_call_count, "Diagnostic run result count mismatch", payload)
            _require(payload["report_id"] is not None, "Diagnostic run did not generate a maturity report", payload)
            _require(payload["action_goal_count"] >= 1, "Diagnostic run did not create report action goals", payload)
            _require(not payload["blockers"], "Diagnostic run should not have blockers with mock providers", payload)

            report_response = client.get(f"/api/projects/{project.id}/maturity-reports/{report_id}", headers=headers)
            report_response.raise_for_status()
            report = report_response.json()
            report_json = report["report_json"]
            metrics = report_json["metrics"]
            coverage = report_json["coverage"]
            keyword_prompt_coverage = report_json["keyword_prompt_coverage"]
            delivery_readiness = report_json["delivery_readiness"]
            _require(metrics["total_answers"] == expected_call_count, "Report total answer count mismatch", metrics)
            _require(metrics["provider_count"] == 3, "Report provider coverage mismatch", metrics)
            _require(coverage["target_question_count"] == 10, "Report target question count mismatch", coverage)
            _require(coverage["keyword_count"] == 10, "Report keyword count mismatch", coverage)
            _require(
                keyword_prompt_coverage["full_coverage_count"] == 10,
                "Report keyword prompt coverage should be complete",
                keyword_prompt_coverage,
            )
            _require(
                delivery_readiness["checks"][0]["ok"] is True,
                "Delivery readiness should pass sample size after one-click diagnostic",
                delivery_readiness,
            )
            _require(
                any(item["key"] == "provider_coverage" and item["ok"] for item in delivery_readiness["checks"]),
                "Delivery readiness should pass provider coverage",
                delivery_readiness,
            )
            real_model_check = next(
                (item for item in delivery_readiness["checks"] if item["key"] == "real_model_samples"),
                None,
            )
            _require(real_model_check is not None, "Delivery readiness missing real model sample check", delivery_readiness)
            _require(
                real_model_check["ok"] is False,
                "Mock diagnostic report should not pass real model sample check",
                delivery_readiness,
            )

            goals_response = client.get(f"/api/projects/{project.id}/stage-goals", headers=headers)
            goals_response.raise_for_status()
            created_goals = [
                goal for goal in goals_response.json() if f"report_id={report_id}" in (goal.get("note") or "")
            ]
            created_goal_ids = [int(goal["id"]) for goal in created_goals]
            _require(
                len(created_goals) == payload["action_goal_count"],
                "Stage goal list should expose diagnostic action goals",
                created_goals,
            )
            _require(
                all(goal.get("suggested_actions") for goal in created_goals),
                "Diagnostic action goals should include suggested actions",
                created_goals,
            )
            audit_rows = list(
                db.scalars(
                    select(AuditLog).where(
                        AuditLog.project_id == project.id,
                        AuditLog.action == "diagnostic_run.create",
                        AuditLog.resource_id == task_id,
                    )
                )
            )
            _require(audit_rows, "Diagnostic run audit log was not recorded")

            result = {
                "ok": True,
                "verification_method": "FastAPI TestClient one-click diagnostic run",
                "project_id": project.id,
                "provider_count": payload["provider_count"],
                "target_question_count": payload["target_question_count"],
                "keyword_count": payload["keyword_count"],
                "prompt_count": payload["prompt_count"],
                "expected_call_count": payload["expected_call_count"],
                "result_count": payload["result_count"],
                "task_id": task_id,
                "task_status": payload["task_status"],
                "report_id": report_id,
                "report_total_answers": metrics["total_answers"],
                "keyword_full_prompt_coverage_count": keyword_prompt_coverage["full_coverage_count"],
                "delivery_readiness_status": delivery_readiness["status"],
                "delivery_readiness_score": delivery_readiness["score"],
                "real_model_sample_check_ok": real_model_check["ok"],
                "created_goal_count": len(created_goals),
                "created_goal_titles": [goal.get("title") for goal in created_goals],
                "audit_log_count": len(audit_rows),
                "safety": {
                    "real_provider_calls": 0,
                    "api_keys_used": False,
                    "temporary_data_cleaned": True,
                },
            }
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        finally:
            result_ids = list(db.scalars(select(CrawlResult.id).where(CrawlResult.project_id == project.id))) if project else []
            task_ids = list(db.scalars(select(CrawlTask.id).where(CrawlTask.project_id == project.id))) if project else []
            if result_ids:
                db.execute(delete(UsageRecord).where(UsageRecord.crawl_result_id.in_(result_ids)))
                db.execute(delete(AnswerAnalysis).where(AnswerAnalysis.crawl_result_id.in_(result_ids)))
                db.execute(delete(MentionedEntity).where(MentionedEntity.crawl_result_id.in_(result_ids)))
                db.execute(delete(CitationSource).where(CitationSource.crawl_result_id.in_(result_ids)))
                db.execute(delete(CrawlResult).where(CrawlResult.id.in_(result_ids)))
            if task_ids:
                db.execute(delete(UsageRecord).where(UsageRecord.task_id.in_(task_ids)))
                db.execute(delete(CrawlTaskLog).where(CrawlTaskLog.task_id.in_(task_ids)))
                db.execute(delete(CrawlTask).where(CrawlTask.id.in_(task_ids)))
            if report_id is not None:
                db.execute(delete(MaturityScoreItem).where(MaturityScoreItem.report_id == report_id))
                db.execute(delete(MaturityReport).where(MaturityReport.id == report_id))
            if created_goal_ids:
                db.execute(delete(ProjectStageGoal).where(ProjectStageGoal.id.in_(created_goal_ids)))
            if task_id is not None and project is not None:
                db.execute(
                    delete(AuditLog).where(
                        AuditLog.project_id == project.id,
                        AuditLog.action == "diagnostic_run.create",
                        AuditLog.resource_id == task_id,
                    )
                )
            if project is not None:
                db.execute(delete(TargetQuestion).where(TargetQuestion.project_id == project.id))
                db.execute(delete(Keyword).where(Keyword.project_id == project.id))
                db.execute(delete(Competitor).where(Competitor.project_id == project.id))
                db.execute(delete(Project).where(Project.id == project.id))
            if provider_ids:
                db.execute(delete(LLMProvider).where(LLMProvider.id.in_(provider_ids)))
            if company is not None:
                db.execute(delete(Company).where(Company.id == company.id))
            db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify one-click diagnostic crawl and maturity report API.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--email", default="geo-demo-e2e@example.com")
    parser.add_argument("--password", default="geo-demo-123")
    args = parser.parse_args()
    result = verify_diagnostic_run(output_path=args.output, email=args.email, password=args.password)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
