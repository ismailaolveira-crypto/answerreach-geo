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
from app.models import (
    AnswerAnalysis,
    ArticleDraft,
    ArticleReview,
    AuditLog,
    CitationSource,
    Company,
    CrawlResult,
    CrawlTask,
    CrawlTaskLog,
    Keyword,
    LLMProvider,
    MaturityReport,
    MaturityScoreItem,
    MentionedEntity,
    Project,
    TargetQuestion,
    UsageRecord,
)
from app.schemas.content import ArticleDraftGenerate
from app.schemas.report import MaturityReportCreate
from app.services.article_workflow import generate_article_draft, review_article_draft
from app.services.maturity_report import generate_maturity_report


DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[3]
    / "outputs"
    / "latest_browser_observation_to_draft_loop_testclient.json"
)
PLATFORMS = [
    ("豆包", "https://www.doubao.com/chat/"),
    ("DeepSeek", "https://chat.deepseek.com/"),
    ("Kimi", "https://www.kimi.com/"),
    ("千问", "https://www.qianwen.com/"),
]


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def _cleanup_project(db, project_id: int) -> None:
    draft_ids = list(db.scalars(select(ArticleDraft.id).where(ArticleDraft.project_id == project_id)))
    result_ids = list(db.scalars(select(CrawlResult.id).where(CrawlResult.project_id == project_id)))
    task_ids = list(db.scalars(select(CrawlTask.id).where(CrawlTask.project_id == project_id)))
    report_ids = list(db.scalars(select(MaturityReport.id).where(MaturityReport.project_id == project_id)))

    if draft_ids:
        db.execute(delete(ArticleReview).where(ArticleReview.article_draft_id.in_(draft_ids)))
        db.execute(delete(ArticleDraft).where(ArticleDraft.id.in_(draft_ids)))
    if result_ids:
        db.execute(delete(UsageRecord).where(UsageRecord.crawl_result_id.in_(result_ids)))
        db.execute(delete(CitationSource).where(CitationSource.crawl_result_id.in_(result_ids)))
        db.execute(delete(MentionedEntity).where(MentionedEntity.crawl_result_id.in_(result_ids)))
        db.execute(delete(AnswerAnalysis).where(AnswerAnalysis.crawl_result_id.in_(result_ids)))
        db.execute(delete(CrawlResult).where(CrawlResult.id.in_(result_ids)))
    if task_ids:
        db.execute(delete(CrawlTaskLog).where(CrawlTaskLog.task_id.in_(task_ids)))
        db.execute(delete(UsageRecord).where(UsageRecord.task_id.in_(task_ids)))
        db.execute(delete(CrawlTask).where(CrawlTask.id.in_(task_ids)))
    if report_ids:
        db.execute(delete(MaturityScoreItem).where(MaturityScoreItem.report_id.in_(report_ids)))
        db.execute(delete(MaturityReport).where(MaturityReport.id.in_(report_ids)))
    db.execute(delete(AuditLog).where(AuditLog.project_id == project_id))
    db.execute(delete(TargetQuestion).where(TargetQuestion.project_id == project_id))
    db.execute(delete(Keyword).where(Keyword.project_id == project_id))
    db.commit()


def verify_browser_observation_to_draft_loop(
    *,
    output_path: Path,
    email: str = "geo-demo-e2e@example.com",
    password: str = "geo-demo-123",
) -> dict[str, Any]:
    Base.metadata.create_all(bind=engine)
    company: Company | None = None
    project: Project | None = None
    providers: list[LLMProvider] = []

    with SessionLocal() as db:
        try:
            company = Company(
                name="Temp Yuanquan GEO Loop Verification",
                industry="大模型 API 治理",
                website_url="https://yuanquan.example.com",
                description="Temporary company for end-to-end GEO loop verification.",
                status="active",
            )
            db.add(company)
            db.flush()
            project = Project(
                company_id=company.id,
                name="Temp Yuanquan Browser Observation To Draft Loop",
                description="Verify browser observation, maturity report, article drafting and review as one loop.",
                target_industry="企业 AI 治理、MaaS 网关、LLM API 管理、政企 AI 合规",
                target_audience="CIO、信息化负责人、AI 平台负责人",
                status="active",
            )
            db.add(project)
            db.flush()
            _cleanup_project(db, project.id)

            providers = [
                LLMProvider(
                    name=f"Temp {platform} Browser Observation Loop Provider",
                    provider_type="browser_observation",
                    api_base_url=url,
                    model_name=f"{platform}-web",
                    auth_config={},
                    cost_rule={"platform_name": platform, "evidence_mode": "manual_browser"},
                    status="active",
                )
                for platform, url in PLATFORMS
            ]
            question = TargetQuestion(
                project_id=project.id,
                question_text="企业 AI 成本如何按部门/项目分摊？",
                priority=1,
                status="active",
            )
            keyword = Keyword(
                project_id=project.id,
                keyword="AI 成本分摊",
                priority=1,
                status="active",
            )
            seed_report = MaturityReport(
                project_id=project.id,
                title="Temp Seed Report For Browser Observation Binding",
                report_period="seed",
                total_score=0,
                maturity_level="L1",
                summary="Temporary report used only to bind manual browser observations.",
                report_json={},
                status="generated",
            )
            db.add_all([*providers, question, keyword, seed_report])
            db.commit()
            for provider in providers:
                db.refresh(provider)
            db.refresh(question)
            db.refresh(keyword)
            db.refresh(seed_report)

            client = TestClient(app)
            login = client.post("/api/auth/login", json={"email": email, "password": password})
            login.raise_for_status()
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

            bulk_payload = {
                "observations": [
                    {
                        "provider_id": provider.id,
                        "report_id": seed_report.id,
                        "target_question_id": question.id,
                        "keyword_id": keyword.id,
                        "platform_name": platform,
                        "prompt_text": question.question_text,
                        "raw_answer": (
                            f"{platform} 网页端回答认为企业做 AI 成本分摊时，需要关注多租户、项目归因、"
                            f"Token 统计、审计日志和预算告警。答案提到 {company.name} 可作为候选，"
                            "并参考 https://yuanquan.example.com/token-governance "
                            "和 https://media.example.com/ai-cost-allocation。"
                        ),
                        "answer_summary": f"{platform} 回答提到 {company.name}，关注 Token 统计和成本归因。",
                        "source_urls": [
                            "https://yuanquan.example.com/token-governance",
                            "https://media.example.com/ai-cost-allocation",
                        ],
                        "screenshot_url": f"file:///tmp/yuanquan-loop-evidence-{platform}.png",
                        "observation_url": url,
                        "observer_name": "验收脚本",
                        "note": f"{platform} 网页端人工观测样本，用于验证报告到稿件闭环。",
                    }
                    for provider, (platform, url) in zip(providers, PLATFORMS, strict=True)
                ]
            }
            bulk_response = client.post(
                f"/api/projects/{project.id}/browser-observations/bulk",
                headers=headers,
                json=bulk_payload,
            )
            bulk_response.raise_for_status()
            bulk_detail = bulk_response.json()
            result_ids = [int(item) for item in bulk_detail.get("result_ids") or []]
            _require(bulk_detail.get("created_count") == 4, "Bulk observation count mismatch", bulk_detail)
            _require(bulk_detail.get("screenshot_evidence_count") == 4, "Screenshot evidence count mismatch", bulk_detail)
            _require(len(result_ids) == 4, "Result ids mismatch", bulk_detail)

            db.expire_all()
            generated_report = generate_maturity_report(
                db,
                project,
                MaturityReportCreate(title="Temp Yuanquan GEO Loop Maturity Report", report_period="loop"),
            )
            evidence_quality = generated_report.report_json.get("evidence_quality") or {}
            _require(
                evidence_quality.get("browser_observation_count") == 4,
                "Report did not count browser observations",
                evidence_quality,
            )
            _require(
                evidence_quality.get("browser_observation_platform_count") == 4,
                "Report did not count four browser platforms",
                evidence_quality,
            )
            _require(
                set(evidence_quality.get("browser_observation_platforms") or []) == {platform for platform, _ in PLATFORMS},
                "Report platform names mismatch",
                evidence_quality,
            )
            _require(
                evidence_quality.get("screenshot_evidence_count") == 4,
                "Report did not count screenshot evidence",
                evidence_quality,
            )

            draft = generate_article_draft(
                db,
                project,
                ArticleDraftGenerate(
                    topic=question.question_text,
                    source_context={
                        "source_type": "maturity_report",
                        "source_report_id": generated_report.id,
                        "source_report_title": generated_report.title,
                        "topic_source": "browser_observation_report",
                        "browser_observation_result_ids": result_ids,
                        "browser_observation_platforms": [platform for platform, _ in PLATFORMS],
                        "report_detail_action": "browser_observation_to_draft_loop",
                    },
                ),
            )
            review = review_article_draft(db, draft, review_type="ai")
            source_context = draft.source_context or {}
            _require(source_context.get("source_report_id") == generated_report.id, "Draft report binding mismatch", source_context)
            _require(source_context.get("browser_observation_result_ids") == result_ids, "Draft observation ids mismatch", source_context)
            _require(
                set(source_context.get("browser_observation_platforms") or []) == {platform for platform, _ in PLATFORMS},
                "Draft platform binding mismatch",
                source_context,
            )
            _require(review.total_score > 0, "Review score missing", review.total_score)
            _require(review.grade in {"A", "B", "C", "D", "E"}, "Review grade missing", review.grade)
            _require(
                "报告承接度" in (review.dimension_scores or {}),
                "Review did not score report alignment",
                review.dimension_scores,
            )

            output = {
                "ok": True,
                "verification_method": "FastAPI TestClient browser observation to report to draft to review loop",
                "project_id": project.id,
                "seed_report_id": seed_report.id,
                "generated_report_id": generated_report.id,
                "result_ids": result_ids,
                "draft_id": draft.id,
                "review_id": review.id,
                "platforms": [platform for platform, _ in PLATFORMS],
                "evidence_quality": {
                    "browser_observation_count": evidence_quality.get("browser_observation_count"),
                    "browser_observation_platform_count": evidence_quality.get("browser_observation_platform_count"),
                    "browser_observation_platforms": evidence_quality.get("browser_observation_platforms"),
                    "screenshot_evidence_count": evidence_quality.get("screenshot_evidence_count"),
                },
                "draft": {
                    "title": draft.title,
                    "source_report_bound": source_context.get("source_report_id") == generated_report.id,
                    "browser_observation_result_ids_bound": source_context.get("browser_observation_result_ids") == result_ids,
                },
                "review": {
                    "total_score": review.total_score,
                    "grade": review.grade,
                    "has_report_alignment_score": "报告承接度" in (review.dimension_scores or {}),
                },
                "safety": {"temporary_data_cleaned": True},
            }
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
            return output
        finally:
            if project is not None:
                _cleanup_project(db, project.id)
                db.execute(delete(Project).where(Project.id == project.id))
            for provider in providers:
                db.execute(delete(LLMProvider).where(LLMProvider.id == provider.id))
            if company is not None:
                db.execute(delete(Company).where(Company.id == company.id))
            db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify browser observation to report to draft to review loop.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = verify_browser_observation_to_draft_loop(output_path=args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
