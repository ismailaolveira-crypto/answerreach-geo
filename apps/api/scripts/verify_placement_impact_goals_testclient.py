import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
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
    Company,
    CrawlResult,
    CrawlTask,
    PlacementRecord,
    Project,
    ProjectStageGoal,
)


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_placement_impact_goals_testclient.json"


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def verify_placement_impact_goals(
    *,
    output_path: Path,
    email: str = "geo-demo-e2e@example.com",
    password: str = "geo-demo-123",
) -> dict[str, Any]:
    Base.metadata.create_all(bind=engine)
    company: Company | None = None
    project: Project | None = None
    task: CrawlTask | None = None
    placement: PlacementRecord | None = None
    crawl_result_ids: list[int] = []
    analysis_ids: list[int] = []
    created_goal_ids: list[int] = []

    with SessionLocal() as db:
        try:
            company = Company(
                name="Temp Placement Impact Goals Verification",
                industry="GEO 投放复盘",
                description="Temporary company for placement impact goal verification.",
                status="active",
            )
            db.add(company)
            db.flush()
            project = Project(
                company_id=company.id,
                name="Temp Placement Impact Goals Project",
                target_industry="GEO SaaS",
                target_audience="市场负责人",
                status="active",
            )
            db.add(project)
            db.flush()
            task = CrawlTask(
                project_id=project.id,
                task_type="manual_batch",
                schedule_type="manual",
                provider_ids=[],
                target_question_ids=[],
                keyword_ids=[],
                status="completed",
            )
            db.add(task)
            db.flush()
            baseline = datetime.now(UTC) - timedelta(days=1)
            placement = PlacementRecord(
                project_id=project.id,
                channel="Temp 复盘投放渠道",
                target_url="https://example.com/temp-geo-placement",
                status="published",
                published_at=baseline,
                visibility="internal",
                delivery_status="ready",
                notes="Temporary placement for impact goal verification.",
            )
            db.add(placement)
            db.flush()

            before_result = CrawlResult(
                task_id=task.id,
                project_id=project.id,
                prompt_text="投放前 GEO 服务商怎么选？",
                raw_answer="投放前答案提及测试公司。",
                status="success",
                collected_at=baseline - timedelta(hours=2),
            )
            after_result = CrawlResult(
                task_id=task.id,
                project_id=project.id,
                prompt_text="投放后 GEO 服务商怎么选？",
                raw_answer="投放后答案暂未提及测试公司。",
                status="success",
                collected_at=baseline + timedelta(hours=2),
            )
            db.add_all([before_result, after_result])
            db.flush()
            crawl_result_ids.extend([before_result.id, after_result.id])
            before_analysis = AnswerAnalysis(
                crawl_result_id=before_result.id,
                company_mentioned=True,
                company_recommended=True,
                sentiment="positive",
                confidence=90,
                analysis_json={},
            )
            after_analysis = AnswerAnalysis(
                crawl_result_id=after_result.id,
                company_mentioned=False,
                company_recommended=False,
                sentiment="neutral",
                confidence=80,
                analysis_json={},
            )
            db.add_all([before_analysis, after_analysis])
            db.flush()
            analysis_ids.extend([before_analysis.id, after_analysis.id])
            db.commit()

            client = TestClient(app)
            login = client.post("/api/auth/login", json={"email": email, "password": password})
            login.raise_for_status()
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

            impact_response = client.get(
                f"/api/projects/{project.id}/placements/{placement.id}/impact",
                headers=headers,
            )
            impact_response.raise_for_status()
            impact = impact_response.json()
            _require(
                impact["review_report"]["status"] == "insufficient_sample",
                "Seed impact should have insufficient sample status",
                impact,
            )

            response = client.post(
                f"/api/projects/{project.id}/placements/{placement.id}/impact/action-goals",
                headers=headers,
            )
            response.raise_for_status()
            goals = response.json()
            created_goal_ids = [int(goal["id"]) for goal in goals]
            metric_keys = {goal.get("metric_key") for goal in goals}
            _require(len(goals) >= 3, "Placement impact should create multiple next-step goals", goals)
            _require("answer_count" in metric_keys, "Missing sample follow-up goal", goals)
            _require("approved_content_count" in metric_keys, "Missing content optimization goal", goals)
            _require("accepted_delivery_count" in metric_keys, "Missing delivery confirmation goal", goals)
            _require(
                all(f"placement_impact_id={placement.id}" in (goal.get("note") or "") for goal in goals),
                "Placement impact goals should carry idempotency marker",
                goals,
            )
            _require(
                any(
                    action.get("action_type") == "run_crawl"
                    for goal in goals
                    for action in (goal.get("suggested_actions") or [])
                ),
                "Impact goals should include crawl suggested action",
                goals,
            )

            second = client.post(
                f"/api/projects/{project.id}/placements/{placement.id}/impact/action-goals",
                headers=headers,
            )
            second.raise_for_status()
            _require(second.json() == [], "Placement impact action goals should be idempotent", second.json())

            tracking_response = client.get(f"/api/projects/{project.id}/stage-goals", headers=headers)
            tracking_response.raise_for_status()
            tracked_goals = [
                goal
                for goal in tracking_response.json()
                if f"placement_impact_id={placement.id}" in (goal.get("note") or "")
            ]
            _require(
                {goal["id"] for goal in tracked_goals} == set(created_goal_ids),
                "Stage goal list should return placement impact goals",
                tracked_goals,
            )
            _require(
                all("progress_rate" in goal and "risk_level" in goal for goal in tracked_goals),
                "Tracked placement impact goals should include progress fields",
                tracked_goals,
            )

            audit_rows = list(
                db.scalars(
                    select(AuditLog).where(
                        AuditLog.action == "placement_impact.action_goal.create",
                        AuditLog.project_id == project.id,
                        AuditLog.resource_id.in_(created_goal_ids),
                    )
                )
            )
            result = {
                "ok": True,
                "verification_method": "FastAPI TestClient placement impact action goals",
                "project_id": project.id,
                "placement_id": placement.id,
                "impact_status": impact["review_report"]["status"],
                "created_goal_count": len(goals),
                "created_goal_metric_keys": sorted(metric_keys),
                "second_call_created_goal_count": len(second.json()),
                "tracked_goal_count": len(tracked_goals),
                "tracking_has_progress": all("progress_rate" in goal for goal in tracked_goals),
                "has_suggested_crawl_action": any(
                    action.get("action_type") == "run_crawl"
                    for goal in goals
                    for action in (goal.get("suggested_actions") or [])
                ),
                "audit_log_count": len(audit_rows),
                "safety": {"temporary_data_cleaned": True},
            }
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        finally:
            if created_goal_ids:
                db.execute(
                    delete(AuditLog).where(
                        AuditLog.action == "placement_impact.action_goal.create",
                        AuditLog.project_id == project.id,
                        AuditLog.resource_id.in_(created_goal_ids),
                    )
                )
                db.execute(delete(ProjectStageGoal).where(ProjectStageGoal.id.in_(created_goal_ids)))
            if analysis_ids:
                db.execute(delete(AnswerAnalysis).where(AnswerAnalysis.id.in_(analysis_ids)))
            if crawl_result_ids:
                db.execute(delete(CrawlResult).where(CrawlResult.id.in_(crawl_result_ids)))
            if placement is not None:
                db.execute(delete(PlacementRecord).where(PlacementRecord.id == placement.id))
            if task is not None:
                db.execute(delete(CrawlTask).where(CrawlTask.id == task.id))
            if project is not None:
                db.execute(delete(Project).where(Project.id == project.id))
            if company is not None:
                db.execute(delete(Company).where(Company.id == company.id))
            db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify placement impact action goals with TestClient.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--email", default="geo-demo-e2e@example.com")
    parser.add_argument("--password", default="geo-demo-123")
    args = parser.parse_args()
    result = verify_placement_impact_goals(
        output_path=args.output,
        email=args.email,
        password=args.password,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
