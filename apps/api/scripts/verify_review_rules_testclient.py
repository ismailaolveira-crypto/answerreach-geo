import argparse
import json
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import delete

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models  # noqa: F401
from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.models import ArticleDraft, ArticleReview, Company, Project, ReviewRule
from app.services.article_workflow import review_article_draft
from app.services.review_rules import seed_default_review_rules


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_review_rules_testclient.json"


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def verify_review_rules(*, output_path: Path, email: str = "geo-demo-e2e@example.com", password: str = "geo-demo-123") -> dict[str, Any]:
    Base.metadata.create_all(bind=engine)
    company: Company | None = None
    project: Project | None = None
    draft: ArticleDraft | None = None
    review: ArticleReview | None = None
    custom_rule: ReviewRule | None = None

    with SessionLocal() as db:
        try:
            rules = seed_default_review_rules(db)
            default_active_rules = [rule for rule in rules if rule.status == "active"]
            _require(len(default_active_rules) >= 8, "Default review rules were not seeded", len(default_active_rules))
            custom_rule = ReviewRule(
                rule_key="verification_unique_marker",
                name="验证自定义规则",
                description="Temporary active rule proving admin-created scoring standards affect article review output.",
                applies_to="article",
                max_score=7,
                weight=1,
                checks_json={"positive_markers": ["验证专属信号"]},
                status="active",
                version=1,
            )
            db.add(custom_rule)
            db.flush()
            active_rules = [*default_active_rules, custom_rule]

            company = Company(
                name="Temp Review Rules Verification",
                industry="GEO 内容审核",
                description="Temporary company for review rule verification.",
                status="active",
            )
            db.add(company)
            db.flush()
            project = Project(
                company_id=company.id,
                name="Temp Review Rules Project",
                target_industry="GEO SaaS",
                target_audience="内容运营",
                status="active",
            )
            db.add(project)
            db.flush()
            draft = ArticleDraft(
                project_id=project.id,
                title="企业如何选择 GEO 优化服务？",
                summary="围绕企业 GEO 优化服务选择标准进行结构化说明。",
                body_text="""# 企业如何选择 GEO 优化服务？

## 一、直接回答

企业选择 GEO 优化服务时，应优先看问题覆盖、案例证据、公开信源和持续监测能力。

## 二、核心判断标准

1. 是否能围绕客户问题形成 FAQ 和解决方案页。
2. 是否有案例、数据、报告或客户来源作为证据。
3. 是否能通过搜索采集持续复盘 AI 答案变化。

## 三、投放与复盘

内容应投放到官网、媒体和解决方案页面，并持续验证 AI 是否引用这些来源。验证专属信号用于确认新增审核标准进入评分结果。
""",
                draft_type="faq_article",
                status="draft",
                generated_by="review_rule_verification",
            )
            db.add(draft)
            db.commit()
            db.refresh(draft)

            review = review_article_draft(db, draft, "ai")
            snapshot = review.review_rule_snapshot or {}
            snapshot_rules = snapshot.get("rules") or []
            _require(review.total_score > 0, "Review score was not generated", review.total_score)
            _require(len(review.dimension_scores) >= 8, "Review dimensions missing", review.dimension_scores)
            _require(snapshot.get("standard") == "GEO 内容审核评分标准", "Review standard snapshot missing", snapshot)
            _require(len(snapshot_rules) >= 8, "Review rule snapshot missing rules", snapshot_rules)
            _require(
                set(review.dimension_scores).issuperset({rule.name for rule in active_rules[:3]}),
                "Dimension scores do not reflect active rules",
                review.dimension_scores,
            )
            _require(
                review.dimension_scores.get(custom_rule.name) == custom_rule.max_score,
                "Custom active rule did not affect dimension scoring",
                review.dimension_scores,
            )
            _require(
                any(rule.get("rule_key") == custom_rule.rule_key for rule in snapshot_rules),
                "Custom active rule missing from review snapshot",
                snapshot_rules,
            )
            client = TestClient(app)
            login = client.post("/api/auth/login", json={"email": email, "password": password})
            login.raise_for_status()
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            api_response = client.get("/api/review-rules", headers=headers)
            api_response.raise_for_status()
            api_rules = api_response.json()
            _require(len(api_rules) >= len(active_rules), "Review rules API did not return seeded rules", api_rules)
            review_response = client.get(
                f"/api/projects/{project.id}/article-drafts/{draft.id}/reviews",
                headers=headers,
            )
            review_response.raise_for_status()
            api_reviews = review_response.json()
            _require(api_reviews, "Article reviews API did not return generated review", api_reviews)
            api_snapshot = api_reviews[0].get("review_rule_snapshot") or {}
            _require(
                any(rule.get("rule_key") == custom_rule.rule_key for rule in api_snapshot.get("rules") or []),
                "Article reviews API did not expose custom rule snapshot",
                api_snapshot,
            )

            result = {
                "ok": True,
                "verification_method": "FastAPI TestClient plus SQLAlchemy review rule snapshot verification",
                "endpoint": "/api/review-rules",
                "seeded_rule_count": len(rules),
                "active_rule_count": len(active_rules),
                "custom_rule_key": custom_rule.rule_key,
                "api_rule_count": len(api_rules),
                "review": {
                    "id": review.id,
                    "total_score": review.total_score,
                    "grade": review.grade,
                    "dimension_count": len(review.dimension_scores),
                    "snapshot_rule_count": len(snapshot_rules),
                    "snapshot_standard": snapshot.get("standard"),
                    "snapshot_total_max_score": snapshot.get("total_max_score"),
                    "custom_rule_score": review.dimension_scores.get(custom_rule.name),
                    "api_snapshot_exposed": True,
                },
                "safety": {"temporary_data_cleaned": True},
            }
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        finally:
            if review is not None:
                db.execute(delete(ArticleReview).where(ArticleReview.id == review.id))
            if custom_rule is not None:
                db.execute(delete(ReviewRule).where(ReviewRule.id == custom_rule.id))
            if draft is not None:
                db.execute(delete(ArticleDraft).where(ArticleDraft.id == draft.id))
            if project is not None:
                db.execute(delete(Project).where(Project.id == project.id))
            if company is not None:
                db.execute(delete(Company).where(Company.id == company.id))
            db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify configurable review rules and review snapshots.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = verify_review_rules(output_path=args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
