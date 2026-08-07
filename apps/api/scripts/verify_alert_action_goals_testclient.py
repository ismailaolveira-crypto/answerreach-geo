import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models  # noqa: F401
from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.models import AuditLog, Company, MaturityReport, Project, ProjectStageGoal, SystemAlert


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_alert_action_goals_testclient.json"


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def verify_alert_action_goals(
    *, output_path: Path, email: str = "geo-demo-e2e@example.com", password: str = "geo-demo-123"
) -> dict[str, Any]:
    Base.metadata.create_all(bind=engine)
    company: Company | None = None
    project: Project | None = None
    report_ids: list[int] = []
    alert_ids: list[int] = []
    goal_ids: list[int] = []

    with SessionLocal() as db:
        try:
            company = Company(
                name="Temp Alert Action Company",
                industry="GEO 告警恢复",
                description="Temporary company for alert action verification.",
                status="active",
            )
            db.add(company)
            db.flush()
            project = Project(
                company_id=company.id,
                name="Temp Alert Action Project",
                target_industry="GEO SaaS",
                target_audience="运营负责人",
                status="active",
            )
            db.add(project)
            db.flush()
            previous = MaturityReport(
                project_id=project.id,
                title="Temp Alert Action Previous Report",
                total_score=84,
                maturity_level="L5 行业权威",
                summary="Previous strong report.",
                report_json={
                    "metrics": {"mention_rate": 0.88, "recommendation_rate": 0.76},
                    "next_content_topics": ["GEO 告警下滑后如何恢复推荐率"],
                    "question_gaps": [{"target_question_id": 101, "question_text": "GEO 推荐率下降怎么办？"}],
                    "keyword_gaps": [{"keyword_id": 202, "keyword": "GEO 监测恢复"}],
                    "source_gaps": [{"domain": "example.com", "mentions": 3, "reason": "高频被提及但未投放"}],
                    "delivery_readiness": {
                        "status": "needs_review",
                        "score": 62,
                        "missing_actions": ["补齐监测下滑解释和整改动作"],
                    },
                },
                status="generated",
                generated_at=datetime.now(UTC) - timedelta(days=3),
            )
            latest = MaturityReport(
                project_id=project.id,
                title="Temp Alert Action Latest Report",
                total_score=58,
                maturity_level="L3 可被识别",
                summary="Latest weaker report.",
                report_json={
                    "metrics": {"mention_rate": 0.45, "recommendation_rate": 0.36},
                    "next_content_topics": ["GEO 告警下滑后如何恢复推荐率"],
                    "question_gaps": [{"target_question_id": 101, "question_text": "GEO 推荐率下降怎么办？"}],
                    "keyword_gaps": [{"keyword_id": 202, "keyword": "GEO 监测恢复"}],
                    "source_gaps": [{"domain": "example.com", "mentions": 3, "reason": "高频被提及但未投放"}],
                    "delivery_readiness": {
                        "status": "needs_review",
                        "score": 62,
                        "missing_actions": ["补齐监测下滑解释和整改动作"],
                    },
                },
                status="generated",
                generated_at=datetime.now(UTC),
            )
            db.add_all([previous, latest])
            db.commit()
            report_ids.extend([previous.id, latest.id])

            client = TestClient(app)
            login = client.post("/api/auth/login", json={"email": email, "password": password})
            login.raise_for_status()
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

            alert_response = client.post(f"/api/alerts/monitoring/run?project_id={project.id}", headers=headers)
            alert_response.raise_for_status()
            alerts = alert_response.json()
            _require(alerts, "Monitoring scan should create alerts", alerts)
            alert = next(item for item in alerts if item["alert_type"] == "monitoring.recommendation_rate_drop")
            alert_ids.extend(int(item["id"]) for item in alerts)

            action_response = client.post(
                f"/api/alerts/{alert['id']}/actions/create-report-action-goals",
                headers=headers,
            )
            action_response.raise_for_status()
            action = action_response.json()
            goal_ids.extend(int(item) for item in action["resource_ids"])
            _require(action["status"] == "created", "Alert action should create goals", action)
            _require(action["detail"]["created_goal_count"] >= 1, "At least one action goal should be created", action)
            _require(action["resource_url"] == f"/projects/{project.id}#stage-goals", "Action goal URL mismatch", action)

            second_response = client.post(
                f"/api/alerts/{alert['id']}/actions/create-report-action-goals",
                headers=headers,
            )
            second_response.raise_for_status()
            second_action = second_response.json()
            _require(second_action["status"] == "already_exists", "Second alert action should be idempotent", second_action)
            _require(
                set(second_action["resource_ids"]) == set(action["resource_ids"]),
                "Second alert action should keep same goal ids",
                second_action,
            )

            refreshed_alert = db.get(SystemAlert, int(alert["id"]))
            _require(refreshed_alert is not None, "Alert should still exist before cleanup", alert)
            _require(refreshed_alert.status == "acknowledged", "Alert should be acknowledged after action", refreshed_alert)
            _require(
                set(refreshed_alert.detail_json.get("action_goal_ids") or []) == set(action["resource_ids"]),
                "Alert detail should store action goal ids",
                refreshed_alert.detail_json,
            )
            goal_count = db.scalar(
                select(func.count()).select_from(ProjectStageGoal).where(ProjectStageGoal.id.in_(goal_ids))
            )
            _require(int(goal_count or 0) == len(set(goal_ids)), "Created goals missing", goal_ids)
            audit_count = db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "alert.action.create_report_action_goals")
                .where(AuditLog.project_id == project.id)
            )
            _require(int(audit_count or 0) >= 2, "Alert action audit logs missing", audit_count)

            result = {
                "ok": True,
                "verification_method": "FastAPI TestClient alert action goals",
                "endpoint": "/api/alerts/{alert_id}/actions/create-report-action-goals",
                "project_id": project.id,
                "alert_id": int(alert["id"]),
                "target_report_id": latest.id,
                "created_goal_count": action["detail"]["created_goal_count"],
                "goal_ids": action["resource_ids"],
                "second_call_status": second_action["status"],
                "alert_status_after_action": refreshed_alert.status,
                "audit_log_count": int(audit_count or 0),
                "safety": {"temporary_data_cleaned": True},
            }
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        finally:
            if goal_ids:
                db.execute(delete(ProjectStageGoal).where(ProjectStageGoal.id.in_(goal_ids)))
            if alert_ids:
                db.execute(delete(SystemAlert).where(SystemAlert.id.in_(alert_ids)))
            if project is not None:
                db.execute(
                    delete(AuditLog)
                    .where(AuditLog.action.in_(["alert.monitoring.run", "alert.action.create_report_action_goals"]))
                    .where(AuditLog.project_id == project.id)
                )
            if report_ids:
                db.execute(delete(MaturityReport).where(MaturityReport.id.in_(report_ids)))
            if project is not None:
                db.execute(delete(Project).where(Project.id == project.id))
            if company is not None:
                db.execute(delete(Company).where(Company.id == company.id))
            db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify alert action goal recovery.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = verify_alert_action_goals(output_path=args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
