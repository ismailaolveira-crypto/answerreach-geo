import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.main import app
from app.models import ArticleDraft, ArticleReview, MaturityReport, Project
from app.schemas.content import ArticleDraftGenerate, ArticleDraftRead
from app.services.article_workflow import generate_article_draft, review_article_draft, revise_article_draft_from_review


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_article_source_context_testclient.json"


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def verify_article_source_context(*, project_id: int, email: str, password: str, output_path: Path) -> dict[str, Any]:
    db = SessionLocal()
    report: MaturityReport | None = None
    draft: ArticleDraft | None = None
    review: ArticleReview | None = None
    revised: ArticleDraft | None = None
    revised_review: ArticleReview | None = None
    try:
        project = db.get(Project, project_id)
        _require(project is not None, "Project not found", project_id)
        now = datetime.now(UTC)
        report = MaturityReport(
            project_id=project.id,
            title="TestClient 稿件来源追踪成熟度报告",
            report_period=now.strftime("%Y-%m-%d"),
            total_score=58,
            maturity_level="L2",
            summary="用于验证报告缺口、阶段目标和稿件来源上下文能闭环。",
            report_json={
                "next_content_topics": ["AI 搜索推荐里如何提升品牌被引用概率"],
                "keyword_gaps": [{"keyword": "AI 搜索推荐"}],
                "question_gaps": [{"question_text": "AI 搜索推荐里如何提升品牌被引用概率"}],
                "source_gaps": [{"domain": "example-media.cn"}, {"url": "https://example.com/faq"}],
                "keyword_prompt_coverage": {
                    "target_variant_count": 3,
                    "keyword_count": 1,
                    "full_coverage_count": 0,
                    "partial_coverage_count": 1,
                    "missing_count": 0,
                    "avg_prompt_variants_per_keyword": 2,
                    "coverage_rate": 0,
                    "items": [
                        {
                            "keyword_id": 999,
                            "keyword": "AI 搜索推荐",
                            "prompt_variant_count": 2,
                            "target_variant_count": 3,
                            "provider_count": 2,
                            "result_count": 4,
                            "coverage_status": "partial",
                            "sample_prompts": [
                                "AI 搜索推荐相关服务商怎么选？",
                                "企业在采购AI 搜索推荐服务时，应该重点比较哪些能力和案例？",
                            ],
                        }
                    ],
                },
            },
            generated_at=now,
        )
        db.add(report)
        db.commit()
        db.refresh(report)

        draft = generate_article_draft(
            db,
            project,
            ArticleDraftGenerate(
                draft_type="stage_goal_article",
                source_context={
                    "stage_goal_id": 987654,
                    "stage_goal_title": "补强 AI 搜索推荐内容承接",
                    "stage_goal_metric_key": "content_readiness",
                    "stage_goal_metric_name": "内容可采信度",
                    "stage_goal_action_type": "generate_draft",
                },
            ),
        )
        context = draft.source_context or {}
        _require(context.get("source_report_id") == report.id, "Draft did not bind latest report", context)
        _require(context.get("stage_goal_id") == 987654, "Draft did not preserve stage goal context", context)
        _require(context.get("topic_source") == "maturity_report", "Draft topic source was not report-driven", context)
        _require(context.get("question_gap_count") == 1, "Question gap count mismatch", context)
        _require(context.get("keyword_gap_count") == 1, "Keyword gap count mismatch", context)
        _require(context.get("source_gap_count") == 2, "Source gap count mismatch", context)
        _require(context.get("keyword_prompt_gap_count") == 1, "Keyword prompt gap count mismatch", context)
        _require(context.get("keyword_prompt_target_variant_count") == 3, "Keyword prompt target variant mismatch", context)
        _require(
            len(context.get("keyword_prompt_samples") or []) == 2,
            "Keyword prompt samples were not carried into source context",
            context,
        )
        _require("example-media.cn" in (context.get("suggested_placement_sources") or []), "Source gap labels missing", context)

        serialized = ArticleDraftRead.model_validate(draft).model_dump()
        _require(
            (serialized.get("source_context") or {}).get("source_report_id") == report.id,
            "ArticleDraftRead did not expose source_context",
            serialized,
        )

        client = TestClient(app)
        login = client.post("/api/auth/login", json={"email": email, "password": password})
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        response = client.get(f"/api/projects/{project.id}/article-drafts/{draft.id}", headers=headers)
        response.raise_for_status()
        api_context = response.json().get("source_context") or {}
        _require(api_context.get("source_report_id") == report.id, "API response missing source context", api_context)

        review = review_article_draft(db, draft, "ai")
        report_alignment = (review.review_rule_snapshot or {}).get("report_alignment") or {}
        _require(report_alignment.get("source_report_id") == report.id, "Review snapshot did not bind report", report_alignment)
        prompt_suggestion = next(
            (item for item in review.suggestions_json if item.get("type") == "keyword_prompt_coverage"),
            None,
        )
        _require(prompt_suggestion is not None, "Review missing keyword prompt coverage suggestion", review.suggestions_json)

        revised = revise_article_draft_from_review(db, draft)
        revised_context = revised.source_context or {}
        _require(revised_context.get("revision_of_draft_id") == draft.id, "Revision missing source draft id", revised_context)
        _require(revised_context.get("source_review_id") == review.id, "Revision missing source review id", revised_context)
        _require(revised_context.get("source_report_id") == report.id, "Revision did not carry report source", revised_context)
        revised_review = review_article_draft(db, revised, "ai")

        result = {
            "ok": True,
            "verification_method": "SQLAlchemy service calls plus FastAPI TestClient serialization",
            "project_id": project.id,
            "report_id": report.id,
            "draft_id": draft.id,
            "review_id": review.id,
            "revised_draft_id": revised.id,
            "source_context": {
                "source_report_id": context.get("source_report_id"),
                "topic_source": context.get("topic_source"),
                "stage_goal_id": context.get("stage_goal_id"),
                "question_gap_count": context.get("question_gap_count"),
                "keyword_gap_count": context.get("keyword_gap_count"),
                "source_gap_count": context.get("source_gap_count"),
                "keyword_prompt_gap_count": context.get("keyword_prompt_gap_count"),
                "keyword_prompt_target_variant_count": context.get("keyword_prompt_target_variant_count"),
                "keyword_prompt_sample_count": len(context.get("keyword_prompt_samples") or []),
                "suggested_placement_sources": context.get("suggested_placement_sources"),
            },
            "review_alignment": report_alignment,
            "keyword_prompt_review_suggestion": prompt_suggestion,
            "revision_context": {
                "revision_of_draft_id": revised_context.get("revision_of_draft_id"),
                "source_review_id": revised_context.get("source_review_id"),
                "source_report_id": revised_context.get("source_report_id"),
            },
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result
    finally:
        if revised_review is not None:
            db.delete(revised_review)
        if revised is not None:
            db.delete(revised)
        if review is not None:
            db.delete(review)
        if draft is not None:
            db.delete(draft)
        if report is not None:
            db.delete(report)
        db.commit()
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify article draft source context and revision inheritance.")
    parser.add_argument("--project-id", type=int, default=9)
    parser.add_argument("--email", default="geo-demo-e2e@example.com")
    parser.add_argument("--password", default="geo-demo-123")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    verify_article_source_context(project_id=args.project_id, email=args.email, password=args.password, output_path=args.output)


if __name__ == "__main__":
    main()
