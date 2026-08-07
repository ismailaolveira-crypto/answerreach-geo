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
from app.models import AuditLog, Company, MaturityReport, MaturityScoreItem, Project, ProjectStageGoal
from app.schemas.report import MaturityReportCreate
from app.services.maturity_report import generate_maturity_report


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_report_action_goals_testclient.json"


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def verify_report_action_goals(
    *,
    output_path: Path,
    email: str = "geo-demo-e2e@example.com",
    password: str = "geo-demo-123",
) -> dict[str, Any]:
    Base.metadata.create_all(bind=engine)
    company: Company | None = None
    project: Project | None = None
    report: MaturityReport | None = None
    created_goal_ids: list[int] = []

    with SessionLocal() as db:
        try:
            company = Company(
                name="Temp Report Action Goals Verification",
                industry="GEO 报告交付",
                description="Temporary company for report action goal verification.",
                status="active",
            )
            db.add(company)
            db.flush()
            project = Project(
                company_id=company.id,
                name="Temp Report Action Goals Project",
                target_industry="GEO SaaS",
                target_audience="市场负责人",
                status="active",
            )
            db.add(project)
            db.flush()
            report = generate_maturity_report(
                db,
                project,
                MaturityReportCreate(title="Temp 交付就绪度报告", report_period="verification"),
            )
            readiness = (report.report_json or {}).get("delivery_readiness") or {}
            _require(readiness.get("status") == "not_ready", "Seed report should require delivery fixes", readiness)

            client = TestClient(app)
            login = client.post("/api/auth/login", json={"email": email, "password": password})
            login.raise_for_status()
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            response = client.post(
                f"/api/projects/{project.id}/maturity-reports/{report.id}/action-goals",
                headers=headers,
            )
            response.raise_for_status()
            goals = response.json()
            created_goal_ids = [int(goal["id"]) for goal in goals]
            delivery_goal = next(
                (
                    goal
                    for goal in goals
                    if "report_delivery_readiness_id=" in (goal.get("note") or "")
                ),
                None,
            )
            _require(goals, "Action goals API did not create any goals", goals)
            _require(delivery_goal is not None, "Delivery readiness action goal was not created", goals)
            _require(
                delivery_goal.get("title") == "报告行动：补齐客户交付质量门槛",
                "Delivery readiness action goal title mismatch",
                delivery_goal,
            )
            _require(
                "待补质量项" in (delivery_goal.get("note") or ""),
                "Delivery readiness goal missing quality fixes",
                delivery_goal,
            )
            suggested_actions = delivery_goal.get("suggested_actions") or []
            _require(suggested_actions, "Delivery readiness goal missing suggested actions", delivery_goal)
            _require(
                any(action.get("action_type") == "run_crawl" for action in suggested_actions),
                "Delivery readiness goal should suggest evidence crawl",
                suggested_actions,
            )
            _require(
                any(action.get("action_type") == "run_real_provider_smoke" for action in suggested_actions),
                "Delivery readiness goal should suggest real provider smoke when real samples are missing",
                suggested_actions,
            )

            second = client.post(
                f"/api/projects/{project.id}/maturity-reports/{report.id}/action-goals",
                headers=headers,
            )
            second.raise_for_status()
            _require(second.json() == [], "Action goals API should be idempotent for same report", second.json())

            tracking_response = client.get(f"/api/projects/{project.id}/stage-goals", headers=headers)
            tracking_response.raise_for_status()
            tracked_goals = [
                goal
                for goal in tracking_response.json()
                if f"report_id={report.id}" in (goal.get("note") or "")
                or f"report_observation_id={report.id}" in (goal.get("note") or "")
                or f"report_delivery_readiness_id={report.id}" in (goal.get("note") or "")
            ]
            _require(
                {goal["id"] for goal in tracked_goals} == set(created_goal_ids),
                "Report action tracking should return created goals with progress fields",
                tracked_goals,
            )
            _require(
                all("progress_rate" in goal and "risk_level" in goal and "suggested_actions" in goal for goal in tracked_goals),
                "Tracked goals should include progress and suggested actions",
                tracked_goals,
            )

            audit_rows = list(
                db.scalars(
                    select(AuditLog).where(
                        AuditLog.action == "maturity_report.action_goal.create",
                        AuditLog.project_id == project.id,
                        AuditLog.resource_id.in_(created_goal_ids),
                    )
                )
            )
            result = {
                "ok": True,
                "verification_method": "FastAPI TestClient report action goals",
                "project_id": project.id,
                "report_id": report.id,
                "created_goal_count": len(goals),
                "created_goal_titles": [goal.get("title") for goal in goals],
                "has_delivery_readiness_goal": delivery_goal is not None,
                "delivery_goal_suggested_actions": [action.get("action_type") for action in suggested_actions],
                "second_call_created_goal_count": len(second.json()),
                "tracked_goal_count": len(tracked_goals),
                "tracked_goal_ids": [goal["id"] for goal in tracked_goals],
                "tracking_has_progress": all("progress_rate" in goal for goal in tracked_goals),
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
                        AuditLog.action == "maturity_report.action_goal.create",
                        AuditLog.project_id == project.id,
                        AuditLog.resource_id.in_(created_goal_ids),
                    )
                )
                db.execute(delete(ProjectStageGoal).where(ProjectStageGoal.id.in_(created_goal_ids)))
            if report is not None:
                db.execute(delete(MaturityScoreItem).where(MaturityScoreItem.report_id == report.id))
                db.execute(delete(MaturityReport).where(MaturityReport.id == report.id))
            if project is not None:
                db.execute(delete(Project).where(Project.id == project.id))
            if company is not None:
                db.execute(delete(Company).where(Company.id == company.id))
            db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify maturity report action-goal API.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--email", default="geo-demo-e2e@example.com")
    parser.add_argument("--password", default="geo-demo-123")
    args = parser.parse_args()
    result = verify_report_action_goals(output_path=args.output, email=args.email, password=args.password)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
