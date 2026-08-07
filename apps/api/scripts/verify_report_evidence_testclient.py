import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models  # noqa: F401
from app.db.session import Base, SessionLocal, engine
from app.models import (
    AnswerAnalysis,
    CitationSource,
    Company,
    CrawlResult,
    CrawlTask,
    Keyword,
    LLMProvider,
    MaturityReport,
    MaturityScoreItem,
    MentionedEntity,
    Project,
    TargetQuestion,
)
from app.schemas.report import MaturityReportCreate
from app.services.maturity_report import generate_maturity_report, render_report_markdown


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_report_evidence_testclient.json"


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def _cleanup_project_artifacts(db, project_id: int) -> None:
    stale_report_ids = list(db.scalars(select(MaturityReport.id).where(MaturityReport.project_id == project_id)))
    if stale_report_ids:
        db.execute(delete(MaturityScoreItem).where(MaturityScoreItem.report_id.in_(stale_report_ids)))
        db.execute(delete(MaturityReport).where(MaturityReport.id.in_(stale_report_ids)))
    stale_result_ids = list(db.scalars(select(CrawlResult.id).where(CrawlResult.project_id == project_id)))
    if stale_result_ids:
        db.execute(delete(MentionedEntity).where(MentionedEntity.crawl_result_id.in_(stale_result_ids)))
        db.execute(delete(CitationSource).where(CitationSource.crawl_result_id.in_(stale_result_ids)))
        db.execute(delete(AnswerAnalysis).where(AnswerAnalysis.crawl_result_id.in_(stale_result_ids)))
        db.execute(delete(CrawlResult).where(CrawlResult.id.in_(stale_result_ids)))
    db.execute(delete(CrawlTask).where(CrawlTask.project_id == project_id))
    db.commit()


def verify_report_evidence(*, output_path: Path) -> dict[str, Any]:
    Base.metadata.create_all(bind=engine)
    company: Company | None = None
    project: Project | None = None
    provider: LLMProvider | None = None
    task: CrawlTask | None = None
    report: MaturityReport | None = None
    result_ids: list[int] = []

    with SessionLocal() as db:
        try:
            company = Company(
                name="Temp Report Evidence Verification",
                industry="GEO 报告",
                description="Temporary company for report evidence verification.",
                status="active",
            )
            db.add(company)
            db.flush()
            project = Project(
                company_id=company.id,
                name="Temp Report Evidence Project",
                target_industry="GEO SaaS",
                target_audience="市场负责人",
                status="active",
            )
            db.add(project)
            db.flush()
            _cleanup_project_artifacts(db, project.id)
            provider = LLMProvider(
                name="Temp Evidence Provider",
                provider_type="openai_compatible",
                model_name="real-evidence-simulated",
                auth_config={"api_key_configured": True, "api_key_redacted": True},
                status="active",
            )
            db.add(provider)
            question = TargetQuestion(
                project_id=project.id,
                question_text="企业 GEO 成熟度报告应该看哪些指标？",
                question_type="core",
                priority=5,
                status="active",
            )
            keyword = Keyword(
                project_id=project.id,
                keyword="GEO 成熟度报告",
                keyword_type="core",
                priority=5,
                status="active",
            )
            db.add_all([question, keyword])
            db.flush()
            task = CrawlTask(
                project_id=project.id,
                task_type="manual_batch",
                schedule_type="manual",
                provider_ids=[provider.id],
                target_question_ids=[question.id],
                keyword_ids=[keyword.id],
                status="success",
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
            )
            db.add(task)
            db.flush()
            samples = [
                (question.id, None, question.question_text, True, True, 1),
                (None, keyword.id, "GEO 成熟度报告相关服务商怎么选？", True, False, None),
                (None, keyword.id, "GEO SaaS领域里，GEO 成熟度报告有哪些值得关注的解决方案或服务商？", True, False, None),
                (None, keyword.id, "企业在采购GEO 成熟度报告服务时，应该重点比较哪些能力和案例？", True, False, None),
            ]
            for question_id, keyword_id, prompt, mentioned, recommended, rank in samples:
                result = CrawlResult(
                    task_id=task.id,
                    project_id=project.id,
                    target_question_id=question_id,
                    keyword_id=keyword_id,
                    provider_id=provider.id,
                    prompt_text=prompt,
                    raw_answer=f"{company.name} 是一个可被提及的 GEO 报告样本答案。",
                    answer_summary=f"{company.name} 在该问题下被{'推荐' if recommended else '提及'}。",
                    status="success",
                    collected_at=datetime.now(UTC),
                )
                db.add(result)
                db.flush()
                result_ids.append(result.id)
                db.add(
                    AnswerAnalysis(
                        crawl_result_id=result.id,
                        company_mentioned=mentioned,
                        company_recommended=recommended,
                        company_rank=rank,
                        sentiment="positive",
                        confidence=90,
                        analysis_json={},
                    )
                )
                db.add(
                    MentionedEntity(
                        crawl_result_id=result.id,
                        entity_name=company.name,
                        entity_type="company",
                        is_company=True,
                        is_competitor=False,
                        mention_count=1,
                        recommendation_rank=rank,
                        context_excerpt="本企业在样本答案中被提及。",
                    )
                )
                if recommended:
                    db.add(
                        MentionedEntity(
                            crawl_result_id=result.id,
                            entity_name="竞品 Alpha GEO",
                            entity_type="competitor",
                            is_company=False,
                            is_competitor=True,
                            mention_count=2,
                            recommendation_rank=2,
                            context_excerpt="竞品也在同一答案中被推荐。",
                        )
                    )
                db.add(
                    CitationSource(
                        crawl_result_id=result.id,
                        source_title="GEO 报告证据页",
                        source_url="https://example.com/geo-report-evidence",
                        source_domain="example.com",
                        source_type="webpage",
                        is_owned=True,
                        is_placed=True,
                        crawlable_score=90,
                        ai_readiness_score=88,
                    )
                )
            db.commit()

            report = generate_maturity_report(
                db,
                project,
                MaturityReportCreate(title="Temp GEO 成熟度证据报告", report_period="verification"),
            )
            items = list(
                db.scalars(
                    select(MaturityScoreItem)
                    .where(MaturityScoreItem.report_id == report.id)
                    .order_by(MaturityScoreItem.id.asc())
                )
            )
            evidence_samples = (report.report_json or {}).get("evidence_samples") or []
            keyword_prompt_coverage = (report.report_json or {}).get("keyword_prompt_coverage") or {}
            brand_matrix = (report.report_json or {}).get("brand_visibility_matrix") or {}
            delivery_readiness = (report.report_json or {}).get("delivery_readiness") or {}
            evidence_quality = (report.report_json or {}).get("evidence_quality") or {}
            markdown = render_report_markdown(report, items)
            _require(evidence_samples, "Report evidence samples missing", report.report_json)
            _require(
                keyword_prompt_coverage.get("full_coverage_count") == 1,
                "Report keyword prompt coverage did not mark the keyword complete",
                keyword_prompt_coverage,
            )
            _require(
                (keyword_prompt_coverage.get("items") or [{}])[0].get("prompt_variant_count") == 3,
                "Report keyword prompt variant count mismatch",
                keyword_prompt_coverage,
            )
            _require(brand_matrix.get("summary"), "Report brand visibility matrix missing summary", brand_matrix)
            _require(brand_matrix.get("by_provider"), "Report brand visibility matrix missing provider breakdown", brand_matrix)
            _require(delivery_readiness.get("checks"), "Report delivery readiness checks missing", delivery_readiness)
            _require(
                delivery_readiness.get("status") in {"ready", "needs_review", "not_ready"},
                "Report delivery readiness status invalid",
                delivery_readiness,
            )
            _require(
                any(item.get("key") == "real_model_samples" and item.get("ok") for item in delivery_readiness["checks"]),
                "Report delivery readiness should pass real model sample check",
                delivery_readiness,
            )
            _require(
                evidence_quality.get("real_api_sample_count") == len(result_ids),
                "Report real API sample count mismatch",
                evidence_quality,
            )
            _require(
                evidence_quality.get("real_provider_count") == 1 and evidence_quality.get("mock_sample_count") == 0,
                "Report real/mock provider evidence split mismatch",
                evidence_quality,
            )
            _require(
                any(item.get("brand_type") == "company" for item in brand_matrix.get("summary", [])),
                "Brand matrix missing company row",
                brand_matrix,
            )
            _require(
                any(item.get("brand_type") == "competitor" for item in brand_matrix.get("summary", [])),
                "Brand matrix missing competitor row",
                brand_matrix,
            )
            _require(
                all(item.get("crawl_result_id") in result_ids for item in evidence_samples[:2]),
                "Evidence samples do not reference crawl results",
                evidence_samples,
            )
            _require(
                all((item.evidence_json or {}).get("supporting_result_ids") for item in items),
                "Score items do not include supporting result ids",
                [item.evidence_json for item in items],
            )
            _require("## 证据样本附录" in markdown, "Markdown export missing evidence appendix")
            _require("## 品牌推荐矩阵" in markdown, "Markdown export missing brand matrix")
            _require("## 交付就绪度" in markdown, "Markdown export missing delivery readiness")
            _require("真实 API 样本数" in markdown, "Markdown export missing real sample count")
            _require("Mock 样本数" in markdown, "Markdown export missing mock sample count")
            _require("关键词语境明细" in markdown, "Markdown export missing keyword prompt coverage detail")
            _require(f"样本 #{result_ids[0]}" in markdown, "Markdown export missing result id evidence")

            result = {
                "ok": True,
                "verification_method": "direct SQLAlchemy maturity report evidence verification",
                "project_id": project.id,
                "report_id": report.id,
                "evidence_sample_count": len(evidence_samples),
                "score_item_count": len(items),
                "brand_matrix_summary_count": len(brand_matrix.get("summary", [])),
                "brand_matrix_provider_count": len(brand_matrix.get("by_provider", [])),
                "brand_matrix_company_position": brand_matrix.get("company_position"),
                "delivery_readiness_status": delivery_readiness.get("status"),
                "delivery_readiness_score": delivery_readiness.get("score"),
                "delivery_readiness_check_count": len(delivery_readiness.get("checks", [])),
                "delivery_readiness_has_real_model_check": any(
                    item.get("key") == "real_model_samples" for item in delivery_readiness.get("checks", [])
                ),
                "real_api_sample_count": evidence_quality.get("real_api_sample_count"),
                "mock_sample_count": evidence_quality.get("mock_sample_count"),
                "real_provider_count": evidence_quality.get("real_provider_count"),
                "real_sample_rate": evidence_quality.get("real_sample_rate"),
                "keyword_prompt_coverage_rate": keyword_prompt_coverage.get("coverage_rate"),
                "keyword_prompt_variant_count": (keyword_prompt_coverage.get("items") or [{}])[0].get("prompt_variant_count"),
                "score_items_with_supporting_ids": sum(
                    1 for item in items if (item.evidence_json or {}).get("supporting_result_ids")
                ),
                "markdown_has_evidence_appendix": "## 证据样本附录" in markdown,
                "markdown_has_brand_matrix": "## 品牌推荐矩阵" in markdown,
                "markdown_has_delivery_readiness": "## 交付就绪度" in markdown,
                "markdown_has_real_sample_quality": "真实 API 样本数" in markdown and "Mock 样本数" in markdown,
                "markdown_has_keyword_prompt_coverage": "关键词语境明细" in markdown,
                "safety": {"temporary_data_cleaned": True},
            }
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        finally:
            if report is not None:
                db.execute(delete(MaturityScoreItem).where(MaturityScoreItem.report_id == report.id))
                db.execute(delete(MaturityReport).where(MaturityReport.id == report.id))
            if result_ids:
                db.execute(delete(MentionedEntity).where(MentionedEntity.crawl_result_id.in_(result_ids)))
                db.execute(delete(CitationSource).where(CitationSource.crawl_result_id.in_(result_ids)))
                db.execute(delete(AnswerAnalysis).where(AnswerAnalysis.crawl_result_id.in_(result_ids)))
                db.execute(delete(CrawlResult).where(CrawlResult.id.in_(result_ids)))
            if task is not None:
                db.execute(delete(CrawlTask).where(CrawlTask.id == task.id))
            if project is not None:
                db.execute(delete(Keyword).where(Keyword.project_id == project.id))
                db.execute(delete(TargetQuestion).where(TargetQuestion.project_id == project.id))
                db.execute(delete(Project).where(Project.id == project.id))
            if provider is not None:
                db.execute(delete(LLMProvider).where(LLMProvider.id == provider.id))
            if company is not None:
                db.execute(delete(Company).where(Company.id == company.id))
            db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify maturity report evidence samples and export appendix.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = verify_report_evidence(output_path=args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
