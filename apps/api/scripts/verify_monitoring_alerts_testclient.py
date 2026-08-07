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
from app.models import AuditLog, Company, MaturityReport, Project, SystemAlert


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_monitoring_alerts_testclient.json"


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def verify_monitoring_alerts(
    *, output_path: Path, email: str = "geo-demo-e2e@example.com", password: str = "geo-demo-123"
) -> dict[str, Any]:
    Base.metadata.create_all(bind=engine)
    company: Company | None = None
    project: Project | None = None
    report_ids: list[int] = []
    alert_ids: list[int] = []

    with SessionLocal() as db:
        try:
            company = Company(
                name="Temp Monitoring Alerts Company",
                industry="GEO 监测",
                description="Temporary company for monitoring alert verification.",
                status="active",
            )
            db.add(company)
            db.flush()
            project = Project(
                company_id=company.id,
                name="Temp Monitoring Alerts Project",
                target_industry="GEO SaaS",
                target_audience="项目负责人",
                status="active",
            )
            db.add(project)
            db.flush()
            previous = MaturityReport(
                project_id=project.id,
                title="Temp Monitoring Previous Report",
                total_score=82,
                maturity_level="L5 行业权威",
                summary="Previous strong report.",
                report_json={
                    "metrics": {
                        "mention_rate": 0.9,
                        "recommendation_rate": 0.8,
                    }
                },
                status="generated",
                generated_at=datetime.now(UTC) - timedelta(days=2),
            )
            latest = MaturityReport(
                project_id=project.id,
                title="Temp Monitoring Latest Report",
                total_score=60,
                maturity_level="L3 可被识别",
                summary="Latest weaker report.",
                report_json={
                    "metrics": {
                        "mention_rate": 0.55,
                        "recommendation_rate": 0.4,
                    }
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
            response = client.post(f"/api/alerts/monitoring/run?project_id={project.id}", headers=headers)
            response.raise_for_status()
            alerts = response.json()
            alert_ids.extend(int(item["id"]) for item in alerts)
            alert_types = {item["alert_type"] for item in alerts}
            _require("monitoring.maturity_score_drop" in alert_types, "Maturity score alert missing", alerts)
            _require("monitoring.mention_rate_drop" in alert_types, "Mention rate alert missing", alerts)
            _require("monitoring.recommendation_rate_drop" in alert_types, "Recommendation rate alert missing", alerts)
            _require(
                all(item["detail_json"].get("target_report_id") == latest.id for item in alerts),
                "Monitoring alerts should reference latest report",
                alerts,
            )

            second = client.post(f"/api/alerts/monitoring/run?project_id={project.id}", headers=headers)
            second.raise_for_status()
            second_alerts = second.json()
            _require(second_alerts == [], "Monitoring alerts should be idempotent for same latest report", second_alerts)

            audit_count = db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "alert.monitoring.run")
                .where(AuditLog.project_id == project.id)
            )
            _require(int(audit_count or 0) >= 2, "Monitoring alert scan audit logs missing", audit_count)

            result = {
                "ok": True,
                "verification_method": "FastAPI TestClient monitoring alert scan",
                "endpoint": "/api/alerts/monitoring/run",
                "project_id": project.id,
                "base_report_id": previous.id,
                "target_report_id": latest.id,
                "created_alert_count": len(alerts),
                "alert_types": sorted(alert_types),
                "second_call_created_alert_count": len(second_alerts),
                "audit_log_count": int(audit_count or 0),
                "safety": {"temporary_data_cleaned": True},
            }
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        finally:
            if alert_ids:
                db.execute(delete(SystemAlert).where(SystemAlert.id.in_(alert_ids)))
            if project is not None:
                db.execute(
                    delete(AuditLog)
                    .where(AuditLog.action == "alert.monitoring.run")
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
    parser = argparse.ArgumentParser(description="Verify monitoring metric alerts.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = verify_monitoring_alerts(output_path=args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
