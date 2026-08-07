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
from app.models import AuditLog, Company, ContentAsset, ContentAssetReview, Project, ProjectStageGoal
from app.services.article_workflow import review_content_asset


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_content_remediation_goals_testclient.json"


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def verify_content_remediation_goals(
    *, output_path: Path, email: str = "geo-demo-e2e@example.com", password: str = "geo-demo-123"
) -> dict[str, Any]:
    Base.metadata.create_all(bind=engine)
    company: Company | None = None
    project: Project | None = None
    asset: ContentAsset | None = None
    review: ContentAssetReview | None = None
    created_goal_ids: list[int] = []

    with SessionLocal() as db:
        try:
            company = Company(
                name="Temp Content Remediation Company",
                industry="GEO 内容整改",
                description="Temporary company for content remediation verification.",
                status="active",
            )
            db.add(company)
            db.flush()
            project = Project(
                company_id=company.id,
                name="Temp Content Remediation Project",
                target_industry="GEO SaaS",
                target_audience="内容运营",
                status="active",
            )
            db.add(project)
            db.flush()
            asset = ContentAsset(
                company_id=company.id,
                project_id=project.id,
                title="历史稿件：泛泛介绍企业服务",
                content_type="article",
                publish_channel="官网",
                source_url="https://example.com/old-article",
                body_text="我们是一家专业公司，提供优质服务，欢迎咨询。",
                status="needs_revision",
            )
            db.add(asset)
            db.commit()
            db.refresh(asset)
            review = review_content_asset(db, asset, "ai")
            _require(review.total_score < 85, "Temporary content asset should need remediation", review.total_score)

            client = TestClient(app)
            login = client.post("/api/auth/login", json={"email": email, "password": password})
            login.raise_for_status()
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            response = client.post(f"/api/projects/{project.id}/content-assets/remediation-goals", headers=headers)
            response.raise_for_status()
            goals = response.json()
            _require(len(goals) == 1, "Expected one remediation goal", goals)
            goal = goals[0]
            created_goal_ids.append(int(goal["id"]))
            _require(goal["metric_key"] == "approved_content_count", "Unexpected remediation goal metric", goal)
            _require("内容整改：" in goal["title"], "Unexpected remediation goal title", goal)
            _require(goal["suggested_actions"], "Remediation goal should include suggested actions", goal)
            _require(
                any(item["action_type"] == "generate_draft" for item in goal["suggested_actions"]),
                "Remediation goal should suggest draft generation",
                goal["suggested_actions"],
            )

            second = client.post(f"/api/projects/{project.id}/content-assets/remediation-goals", headers=headers)
            second.raise_for_status()
            second_goals = second.json()
            _require(second_goals == [], "Remediation goal API should be idempotent", second_goals)

            audit_count = db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "content_asset.remediation_goal.create")
                .where(AuditLog.project_id == project.id)
                .where(AuditLog.resource_id == goal["id"])
            )
            _require(int(audit_count) >= 1, "Remediation goal audit log missing", goal)

            result = {
                "ok": True,
                "verification_method": "FastAPI TestClient content asset remediation goals",
                "endpoint": f"/api/projects/{project.id}/content-assets/remediation-goals",
                "project_id": project.id,
                "asset_id": asset.id,
                "review_score": review.total_score,
                "created_goal_count": len(goals),
                "created_goal_id": goal["id"],
                "suggested_actions": [item["action_type"] for item in goal["suggested_actions"]],
                "second_call_created_goal_count": len(second_goals),
                "audit_log_count": int(audit_count),
                "safety": {"temporary_data_cleaned": True},
            }
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        finally:
            if created_goal_ids:
                db.execute(
                    delete(AuditLog)
                    .where(AuditLog.action == "content_asset.remediation_goal.create")
                    .where(AuditLog.project_id == (project.id if project else -1))
                    .where(AuditLog.resource_id.in_(created_goal_ids))
                )
                db.execute(delete(ProjectStageGoal).where(ProjectStageGoal.id.in_(created_goal_ids)))
            if review is not None:
                db.execute(delete(ContentAssetReview).where(ContentAssetReview.id == review.id))
            if asset is not None:
                db.execute(delete(ContentAsset).where(ContentAsset.id == asset.id))
            if project is not None:
                db.execute(delete(Project).where(Project.id == project.id))
            if company is not None:
                db.execute(delete(Company).where(Company.id == company.id))
            db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify content asset remediation stage goals.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = verify_content_remediation_goals(output_path=args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
