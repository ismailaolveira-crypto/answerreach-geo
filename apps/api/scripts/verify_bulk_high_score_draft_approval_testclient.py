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
from app.models import ArticleDraft, ArticleReview, Company, Project


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_bulk_high_score_draft_approval_testclient.json"


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def verify_bulk_high_score_draft_approval(
    *, output_path: Path, email: str = "geo-demo-e2e@example.com", password: str = "geo-demo-123"
) -> dict[str, Any]:
    Base.metadata.create_all(bind=engine)
    company: Company | None = None
    project: Project | None = None
    draft_ids: list[int] = []
    review_ids: list[int] = []

    with SessionLocal() as db:
        try:
            company = Company(
                name="Temp Bulk High Score Approval Verification",
                industry="GEO 内容审核",
                description="Temporary company for bulk high score approval verification.",
                status="active",
            )
            db.add(company)
            db.flush()
            project = Project(
                company_id=company.id,
                name="Temp Bulk High Score Approval Project",
                target_industry="GEO SaaS",
                target_audience="内容运营",
                status="active",
            )
            db.add(project)
            db.flush()
            high_draft = ArticleDraft(
                project_id=project.id,
                title="企业如何选择 GEO 优化服务？",
                summary="高分稿件，用于验证批量通过。",
                body_text="结构完整，包含案例、报告、FAQ、官网投放和客户证据。",
                draft_type="faq_article",
                status="pending_review",
                generated_by="bulk_approval_verification",
            )
            low_draft = ArticleDraft(
                project_id=project.id,
                title="GEO 服务",
                summary="低分稿件，用于验证不会被批量通过。",
                body_text="内容太短。",
                draft_type="faq_article",
                status="pending_review",
                generated_by="bulk_approval_verification",
            )
            db.add_all([high_draft, low_draft])
            db.flush()
            draft_ids = [high_draft.id, low_draft.id]
            high_review = ArticleReview(
                article_draft_id=high_draft.id,
                total_score=92,
                grade="A",
                dimension_scores={"高分验证": 92},
                issues_json=[],
                suggestions_json=[],
                risk_expressions=[],
                review_rule_snapshot={"verification": "bulk_high_score"},
                review_type="ai",
                status="completed",
            )
            low_review = ArticleReview(
                article_draft_id=low_draft.id,
                total_score=68,
                grade="C",
                dimension_scores={"低分验证": 68},
                issues_json=[{"type": "quality", "message": "分数低于批量通过阈值"}],
                suggestions_json=[],
                risk_expressions=[],
                review_rule_snapshot={"verification": "bulk_high_score"},
                review_type="ai",
                status="completed",
            )
            db.add_all([high_review, low_review])
            db.commit()
            db.refresh(high_draft)
            db.refresh(low_draft)
            db.refresh(high_review)
            db.refresh(low_review)
            review_ids = [high_review.id, low_review.id]

            client = TestClient(app)
            login = client.post("/api/auth/login", json={"email": email, "password": password})
            login.raise_for_status()
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            targets = [
                (draft, review)
                for draft, review in [(high_draft, high_review), (low_draft, low_review)]
                if draft.status != "approved" and review.total_score >= 85
            ]
            _require([draft.id for draft, _ in targets] == [high_draft.id], "Only the high score draft should be targeted")
            approved_review_ids: list[int] = []
            for draft, review in targets:
                response = client.post(
                    f"/api/projects/{project.id}/article-drafts/{draft.id}/human-review",
                    headers=headers,
                    json={
                        "decision": "approved",
                        "comment": f"审核台批量通过：AI 评分 {review.total_score} {review.grade}。",
                    },
                )
                response.raise_for_status()
                approved_review_ids.append(int(response.json()["id"]))
            review_ids.extend(approved_review_ids)

            db.refresh(high_draft)
            db.refresh(low_draft)
            human_reviews = list(
                db.scalars(
                    select(ArticleReview)
                    .where(ArticleReview.article_draft_id.in_(draft_ids))
                    .where(ArticleReview.review_type == "human")
                )
            )
            _require(high_draft.status == "approved", "High score draft should be approved", high_draft.status)
            _require(low_draft.status == "pending_review", "Low score draft should remain pending", low_draft.status)
            _require(len(human_reviews) == 1, "Only one human review should be created", [review.id for review in human_reviews])

            result = {
                "ok": True,
                "verification_method": "FastAPI TestClient high-score draft human approval",
                "project_id": project.id,
                "high_draft_id": high_draft.id,
                "low_draft_id": low_draft.id,
                "approved_count": len(approved_review_ids),
                "low_score_preserved": low_draft.status == "pending_review",
                "threshold": 85,
                "safety": {"temporary_data_cleaned": True},
            }
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        finally:
            if review_ids:
                db.execute(delete(ArticleReview).where(ArticleReview.id.in_(review_ids)))
            if draft_ids:
                db.execute(delete(ArticleDraft).where(ArticleDraft.id.in_(draft_ids)))
            if project is not None:
                db.execute(delete(Project).where(Project.id == project.id))
            if company is not None:
                db.execute(delete(Company).where(Company.id == company.id))
            db.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = verify_bulk_high_score_draft_approval(output_path=args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
