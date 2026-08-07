import argparse
import json
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models  # noqa: F401
from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.models import Company, CrawlResult, CrawlTask, CrawlTaskLog, Keyword, LLMProvider, Project, TargetQuestion


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_crawl_estimate_cost_testclient.json"
PROJECT_PAGE = Path(__file__).resolve().parents[3] / "apps" / "web" / "app" / "(app)" / "projects" / "[id]" / "page.tsx"


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def verify_crawl_estimate_cost(
    *, output_path: Path, email: str = "geo-demo-e2e@example.com", password: str = "geo-demo-123"
) -> dict[str, Any]:
    Base.metadata.create_all(bind=engine)
    company: Company | None = None
    project: Project | None = None
    providers: list[LLMProvider] = []
    created_task_ids: list[int] = []

    with SessionLocal() as db:
        try:
            company = Company(
                name="Temp Crawl Estimate Cost Verification",
                industry="GEO 验收",
                description="Temporary company for crawl estimate cost verification.",
                status="active",
            )
            db.add(company)
            db.flush()
            project = Project(
                company_id=company.id,
                name="Temp Crawl Estimate Cost Project",
                description="Temporary project for crawl estimate cost verification.",
                target_industry="GEO SaaS",
                target_audience="B2B marketing team",
                status="active",
            )
            db.add(project)
            db.flush()
            priced_provider = LLMProvider(
                name="Temp Priced Estimate Provider",
                provider_type="mock",
                model_name="mock-geo-search",
                auth_config={},
                cost_rule={"input_per_1k": 0.002, "output_per_1k": 0.006, "currency": "USD"},
                status="active",
            )
            unpriced_provider = LLMProvider(
                name="Temp Unpriced Real Estimate Provider",
                provider_type="openai_compatible",
                api_base_url="https://example.invalid",
                model_name="example-model",
                auth_config={"api_key": "temp-placeholder", "endpoint_path": "/v1/chat/completions"},
                cost_rule={},
                status="active",
            )
            db.add_all([priced_provider, unpriced_provider])
            db.flush()
            providers = [priced_provider, unpriced_provider]
            question = TargetQuestion(
                project_id=project.id,
                question_text="企业做 GEO 优化服务应该怎么选？",
                question_type="core",
                priority=5,
                status="active",
            )
            keyword = Keyword(
                project_id=project.id,
                keyword="GEO 优化服务",
                keyword_type="core",
                priority=5,
                status="active",
            )
            db.add_all([question, keyword])
            db.commit()

            client = TestClient(app)
            login = client.post("/api/auth/login", json={"email": email, "password": password})
            login.raise_for_status()
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            response = client.post(
                f"/api/projects/{project.id}/crawl-tasks/estimate",
                headers=headers,
                json={
                    "provider_ids": [priced_provider.id, unpriced_provider.id],
                    "target_question_ids": [question.id],
                    "keyword_ids": [keyword.id],
                    "execute_now": False,
                },
            )
            response.raise_for_status()
            estimate = response.json()
            provider_items = {item["id"]: item for item in estimate["providers"]}

            _require(estimate["prompt_count"] == 4, "Question plus keyword variants should create four prompts", estimate)
            _require(estimate["total_call_count"] == 8, "Two providers should double the call count", estimate)
            _require(estimate["estimated_total_tokens"] > 0, "Estimated tokens should be present", estimate)
            _require(estimate["estimated_cost"] > 0, "Priced provider should contribute estimated cost", estimate)
            _require(
                estimate["cost_configured_provider_count"] == 1,
                "Only one provider should have cost configured",
                estimate,
            )
            _require(
                provider_items[priced_provider.id]["cost_configured"] is True,
                "Priced provider should be marked cost-configured",
                provider_items,
            )
            _require(
                provider_items[unpriced_provider.id]["cost_configured"] is False,
                "Unpriced provider should be marked unconfigured",
                provider_items,
            )
            _require(
                any("未配置输入/输出单价" in warning for warning in estimate["warnings"]),
                "Unpriced real provider warning should be shown",
                estimate["warnings"],
            )
            budget_response = client.post(
                f"/api/projects/{project.id}/crawl-tasks",
                headers=headers,
                json={
                    "provider_ids": [priced_provider.id, unpriced_provider.id],
                    "target_question_ids": [question.id],
                    "keyword_ids": [keyword.id],
                    "execute_now": True,
                    "max_estimated_cost": 0.000001,
                },
            )
            budget_response.raise_for_status()
            budget_task = budget_response.json()
            created_task_ids.append(int(budget_task["id"]))
            result_count = db.scalar(
                select(func.count()).select_from(CrawlResult).where(CrawlResult.task_id == budget_task["id"])
            )
            _require(budget_task["status"] == "failed", "Over-budget task should fail before execution", budget_task)
            _require(
                "Budget guard blocked crawl" in (budget_task["error_message"] or ""),
                "Over-budget task should explain budget guard",
                budget_task,
            )
            _require(int(result_count or 0) == 0, "Over-budget task should not create crawl results", result_count)
            diagnostic_response = client.post(
                f"/api/projects/{project.id}/diagnostic-runs",
                headers=headers,
                json={
                    "provider_ids": [priced_provider.id, unpriced_provider.id],
                    "target_question_ids": [question.id],
                    "keyword_ids": [keyword.id],
                    "execute_now": True,
                    "generate_report": True,
                    "create_action_goals": True,
                    "max_estimated_cost": 0.000001,
                    "title": "Temp over-budget diagnostic verification",
                    "report_period": "budget_guard_verification",
                },
            )
            diagnostic_response.raise_for_status()
            diagnostic_result = diagnostic_response.json()
            created_task_ids.append(int(diagnostic_result["task_id"]))
            diagnostic_result_count = db.scalar(
                select(func.count()).select_from(CrawlResult).where(CrawlResult.task_id == diagnostic_result["task_id"])
            )
            _require(
                diagnostic_result["task_status"] == "failed",
                "Over-budget diagnostic should create a failed task",
                diagnostic_result,
            )
            _require(
                diagnostic_result["report_id"] is None,
                "Over-budget diagnostic should not generate a report",
                diagnostic_result,
            )
            _require(
                int(diagnostic_result_count or 0) == 0,
                "Over-budget diagnostic should not create crawl results",
                diagnostic_result_count,
            )
            _require(
                diagnostic_result["estimated_cost"] == estimate["estimated_cost"],
                "Diagnostic should expose the same estimated cost as preflight estimate",
                diagnostic_result,
            )
            project_page_source = PROJECT_PAGE.read_text(encoding="utf-8")
            _require(
                "diagnostic_estimated_cost" in project_page_source
                and "diagnostic_estimated_tokens" in project_page_source
                and "成本约" in project_page_source,
                "Project page should surface diagnostic estimated token/cost feedback",
                str(PROJECT_PAGE),
            )

            result = {
                "ok": True,
                "verification_method": "FastAPI TestClient, cost estimate plus budget guard, no real provider calls",
                "project_id": project.id,
                "endpoint": f"/api/projects/{project.id}/crawl-tasks/estimate",
                "prompt_count": estimate["prompt_count"],
                "total_call_count": estimate["total_call_count"],
                "estimated_total_tokens": estimate["estimated_total_tokens"],
                "estimated_cost": estimate["estimated_cost"],
                "currency": estimate["currency"],
                "cost_configured_provider_count": estimate["cost_configured_provider_count"],
                "warnings": estimate["warnings"],
                "budget_guard": {
                    "task_id": budget_task["id"],
                    "task_status": budget_task["status"],
                    "blocked_without_results": int(result_count or 0) == 0,
                },
                "diagnostic_budget_guard": {
                    "task_id": diagnostic_result["task_id"],
                    "task_status": diagnostic_result["task_status"],
                    "report_id": diagnostic_result["report_id"],
                    "estimated_cost": diagnostic_result["estimated_cost"],
                    "blocked_without_results": int(diagnostic_result_count or 0) == 0,
                },
                "ui_feedback": {
                    "project_page": str(PROJECT_PAGE),
                    "shows_diagnostic_estimated_cost": True,
                    "shows_diagnostic_estimated_tokens": True,
                },
                "safety": {
                    "execute_now": False,
                    "real_provider_calls": 0,
                    "temporary_data_cleaned": True,
                },
            }
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        finally:
            if created_task_ids:
                db.execute(delete(CrawlTaskLog).where(CrawlTaskLog.task_id.in_(created_task_ids)))
                db.execute(delete(CrawlTask).where(CrawlTask.id.in_(created_task_ids)))
            if project is not None:
                db.execute(delete(TargetQuestion).where(TargetQuestion.project_id == project.id))
                db.execute(delete(Keyword).where(Keyword.project_id == project.id))
                db.execute(delete(Project).where(Project.id == project.id))
            if company is not None:
                db.execute(delete(Company).where(Company.id == company.id))
            if providers:
                db.execute(delete(LLMProvider).where(LLMProvider.id.in_([provider.id for provider in providers])))
            db.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = verify_crawl_estimate_cost(output_path=args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
