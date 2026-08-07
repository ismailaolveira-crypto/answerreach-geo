import argparse
import json
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.main import app
from app.api.routes.projects import _project_mvp_status
from app.models import (
    ArticleDraft,
    ArticleReview,
    Company,
    DeliveryPackageAccessLog,
    DeliveryPackageShare,
    MaturityReport,
    PlacementRecord,
    Project,
    User,
)
from app.schemas.content import ArticleDraftGenerate
from app.services.article_workflow import decide_article_draft_review, generate_article_draft, review_article_draft


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_content_delivery_loop_testclient.json"


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def _verify_placement_next_action(db) -> dict[str, Any]:
    company: Company | None = None
    project: Project | None = None
    draft: ArticleDraft | None = None
    ai_review: ArticleReview | None = None
    human_review: ArticleReview | None = None
    try:
        user = db.scalar(select(User).order_by(User.id.asc()).limit(1))
        _require(user is not None, "User not found for MVP status verification")
        company = Company(
            name="Temp Content Delivery Next Action Verification",
            industry="GEO 内容交付",
            status="active",
        )
        db.add(company)
        db.flush()
        project = Project(
            company_id=company.id,
            name="Temp Content Delivery Next Action Project",
            target_industry="GEO SaaS",
            target_audience="内容运营",
            status="active",
        )
        db.add(project)
        db.flush()
        draft = generate_article_draft(db, project, ArticleDraftGenerate(topic="GEO 内容交付下一步动作验证"))
        ai_review = review_article_draft(db, draft, "ai")
        human_review = decide_article_draft_review(
            db,
            draft,
            reviewer_id=None,
            decision="approved",
            comment="TestClient 验证：通过稿件后应进入投放计划。",
        )
        db.commit()
        status = _project_mvp_status(db, project, user)
        content_delivery = status.content_delivery
        _require(content_delivery is not None, "Content delivery summary missing")
        _require(
            content_delivery.next_action_type == "create_placement",
            "Content delivery next action should ask for placement creation",
            content_delivery,
        )
        _require(
            content_delivery.next_action_url == f"/projects/{project.id}/placements",
            "Placement next action should point to placement workbench",
            content_delivery,
        )
        return {
            "project_id": project.id,
            "draft_id": draft.id,
            "next_action_type": content_delivery.next_action_type,
            "next_action_url": content_delivery.next_action_url,
        }
    finally:
        if human_review is not None:
            db.delete(human_review)
        if ai_review is not None:
            db.delete(ai_review)
        if draft is not None:
            db.delete(draft)
        if project is not None:
            db.delete(project)
        if company is not None:
            db.delete(company)
        db.commit()


def verify_content_delivery_loop(*, project_id: int, output_path: Path) -> dict[str, Any]:
    db = SessionLocal()
    draft: ArticleDraft | None = None
    ai_review: ArticleReview | None = None
    human_review: ArticleReview | None = None
    placement: PlacementRecord | None = None
    share: DeliveryPackageShare | None = None
    try:
        pre_placement_next_action = _verify_placement_next_action(db)
        project = db.get(Project, project_id)
        _require(project is not None, "Project not found", project_id)
        report = db.scalar(
            select(MaturityReport)
            .where(MaturityReport.project_id == project_id)
            .order_by(MaturityReport.id.desc())
            .limit(1)
        )
        topic = (
            (report.report_json.get("next_content_topics") if report is not None else None)
            or ["GEO 优化测试选题"]
        )[0]

        draft = generate_article_draft(db, project, ArticleDraftGenerate(topic=topic))
        ai_review = review_article_draft(db, draft, "ai")
        human_review = decide_article_draft_review(
            db,
            draft,
            reviewer_id=None,
            decision="approved",
            comment="TestClient 验证：人工通过并进入投放。",
        )

        placement = PlacementRecord(
            project_id=project.id,
            article_draft_id=draft.id,
            channel="TestClient 后半段闭环投放",
            status="planned",
            notes="TestClient 验证：报告选题生成稿件后进入投放。",
        )
        db.add(placement)
        db.flush()
        placement.status = "published"
        placement.published_at = datetime.now(UTC)
        placement.visibility = "customer_visible"
        placement.delivery_status = "ready"
        placement.archive_note = "TestClient 验证：发布并进入客户交付包。"

        share = DeliveryPackageShare(
            project_id=project.id,
            token=secrets.token_urlsafe(24),
            name="TestClient 客户交付包",
            status="active",
        )
        db.add(share)
        db.commit()
        db.refresh(draft)
        db.refresh(ai_review)
        db.refresh(human_review)
        db.refresh(placement)
        db.refresh(share)

        client = TestClient(app)
        package_response = client.get(f"/api/public/delivery-packages/{share.token}")
        package_response.raise_for_status()
        package_data = package_response.json()
        deliverables = package_data.get("deliverables") or []
        delivered_item = next(
            (item for item in deliverables if int((item.get("placement") or {}).get("id") or 0) == placement.id),
            None,
        )
        _require(delivered_item is not None, "Public delivery package did not include temporary placement", package_data)

        confirm_response = client.post(
            f"/api/public/delivery-packages/{share.token}/placements/{placement.id}/confirm",
            json={"actor_name": "TestClient", "comment": "确认后半段闭环可用。"},
        )
        confirm_response.raise_for_status()
        db.refresh(placement)
        _require(placement.delivery_status == "accepted", "Public confirmation did not mark placement accepted", placement.delivery_status)

        result = {
            "ok": True,
            "verification_method": "FastAPI TestClient plus direct SQLAlchemy setup, no local port binding",
            "project_id": project.id,
            "topic": topic,
            "draft": {
                "id": draft.id,
                "status": draft.status,
                "title": draft.title,
            },
            "ai_review": {
                "id": ai_review.id,
                "score": ai_review.total_score,
                "grade": ai_review.grade,
            },
            "human_review": {
                "id": human_review.id,
                "status": human_review.status,
            },
            "pre_placement_next_action": {
                "temporary_project_id": pre_placement_next_action["project_id"],
                "next_action_type": pre_placement_next_action["next_action_type"],
                "next_action_url": pre_placement_next_action["next_action_url"],
            },
            "placement": {
                "id": placement.id,
                "status": placement.status,
                "visibility": placement.visibility,
                "delivery_status": placement.delivery_status,
                "published_at_set": placement.published_at is not None,
            },
            "share": {
                "id": share.id,
                "status": share.status,
                "token_length": len(share.token),
                "public_path": f"/share/delivery/{share.token}",
            },
            "public_package": {
                "deliverable_count": len(deliverables),
                "temporary_placement_visible": delivered_item is not None,
            },
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result
    finally:
        if share is not None:
            for log in db.scalars(select(DeliveryPackageAccessLog).where(DeliveryPackageAccessLog.share_id == share.id)):
                db.delete(log)
            db.delete(share)
        if placement is not None:
            db.delete(placement)
        if human_review is not None:
            db.delete(human_review)
        if ai_review is not None:
            db.delete(ai_review)
        if draft is not None:
            db.delete(draft)
        db.commit()
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify report-to-public-delivery content loop with TestClient.")
    parser.add_argument("--project-id", type=int, default=9)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    verify_content_delivery_loop(project_id=args.project_id, output_path=args.output)


if __name__ == "__main__":
    main()
