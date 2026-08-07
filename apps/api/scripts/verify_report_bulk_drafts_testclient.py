import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import delete

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models  # noqa: F401
from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.models import ArticleDraft, ArticleReview, Company, MaturityReport, Project


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_report_bulk_drafts_testclient.json"


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def verify_report_bulk_drafts(
    *, output_path: Path, email: str = "geo-demo-e2e@example.com", password: str = "geo-demo-123"
) -> dict[str, Any]:
    Base.metadata.create_all(bind=engine)
    company: Company | None = None
    project: Project | None = None
    report: MaturityReport | None = None
    draft_ids: list[int] = []
    review_ids: list[int] = []
    topics = [
        "AI 搜索结果里如何提升品牌被引用概率",
        "GEO 优化服务商选择时应该重点看什么",
        "企业如何把官网 FAQ 改造成 AI 可引用内容",
    ]

    with SessionLocal() as db:
        try:
            company = Company(
                name="Temp Report Bulk Drafts Verification",
                industry="GEO 内容",
                description="Temporary company for report bulk draft verification.",
                status="active",
            )
            db.add(company)
            db.flush()
            project = Project(
                company_id=company.id,
                name="Temp Report Bulk Drafts Project",
                target_industry="GEO SaaS",
                target_audience="市场负责人",
                status="active",
            )
            db.add(project)
            db.flush()
            report = MaturityReport(
                project_id=project.id,
                title="Temp 批量撰稿成熟度报告",
                report_period="bulk_draft_verification",
                total_score=62,
                maturity_level="L4",
                summary="用于验证报告选题批量生成稿件并评分。",
                report_json={
                    "next_content_topics": topics,
                    "question_gaps": [{"question_text": topics[1]}],
                    "keyword_gaps": [{"keyword": "官网 FAQ AI 可引用"}],
                },
                status="generated",
                generated_at=datetime.now(UTC),
            )
            db.add(report)
            db.commit()
            db.refresh(report)

            client = TestClient(app)
            login = client.post("/api/auth/login", json={"email": email, "password": password})
            login.raise_for_status()
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            for index, topic in enumerate(topics, start=1):
                draft_response = client.post(
                    f"/api/projects/{project.id}/article-drafts/generate",
                    headers=headers,
                    json={
                        "topic": topic,
                        "source_context": {
                            "source_type": "maturity_report",
                            "source_report_id": report.id,
                            "source_report_title": report.title,
                            "topic_source": "maturity_report",
                            "report_detail_action": "bulk_topic_generate_review",
                            "bulk_topic_index": index,
                            "bulk_topic_count": len(topics),
                        },
                    },
                )
                draft_response.raise_for_status()
                draft = draft_response.json()
                draft_ids.append(int(draft["id"]))
                context = draft.get("source_context") or {}
                _require(context.get("source_report_id") == report.id, "Draft should bind current report", context)
                _require(
                    context.get("report_detail_action") == "bulk_topic_generate_review",
                    "Draft should record bulk report action",
                    context,
                )
                review_response = client.post(
                    f"/api/projects/{project.id}/article-drafts/{draft['id']}/reviews",
                    headers=headers,
                    json={"review_type": "ai"},
                )
                review_response.raise_for_status()
                review = review_response.json()
                review_ids.append(int(review["id"]))
                _require(review["grade"] in {"A", "B", "C", "D", "E"}, "Review grade should be present", review)

            result = {
                "ok": True,
                "verification_method": "FastAPI TestClient report topics to drafts and reviews",
                "project_id": project.id,
                "report_id": report.id,
                "topic_count": len(topics),
                "draft_count": len(draft_ids),
                "review_count": len(review_ids),
                "draft_ids": draft_ids,
                "review_ids": review_ids,
                "source_report_bound": True,
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
            if report is not None:
                db.execute(delete(MaturityReport).where(MaturityReport.id == report.id))
            if project is not None:
                db.execute(delete(Project).where(Project.id == project.id))
            if company is not None:
                db.execute(delete(Company).where(Company.id == company.id))
            db.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = verify_report_bulk_drafts(output_path=args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
