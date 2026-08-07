import argparse
import json
import sys
from datetime import UTC, datetime
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
    AuditLog,
    CitationSource,
    Company,
    CrawlResult,
    CrawlTask,
    LLMProvider,
    MaturityReport,
    MaturityScoreItem,
    Project,
    ReportTemplate,
    TargetQuestion,
)
from app.schemas.report import MaturityReportCreate
from app.services.maturity_report import generate_maturity_report, render_report_markdown
from app.services.report_templates import seed_default_report_template


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_report_templates_testclient.json"


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def verify_report_templates(
    *, output_path: Path, email: str = "geo-demo-e2e@example.com", password: str = "geo-demo-123"
) -> dict[str, Any]:
    Base.metadata.create_all(bind=engine)
    company: Company | None = None
    project: Project | None = None
    provider: LLMProvider | None = None
    task: CrawlTask | None = None
    report: MaturityReport | None = None
    template_id: int | None = None

    with SessionLocal() as db:
        try:
            default_template = seed_default_report_template(db)
            client = TestClient(app)
            login = client.post("/api/auth/login", json={"email": email, "password": password})
            login.raise_for_status()
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            list_response = client.get("/api/report-templates", headers=headers)
            list_response.raise_for_status()
            templates = list_response.json()
            _require(templates, "Report template API did not return templates", templates)
            _require(
                any(item["template_key"] == default_template.template_key for item in templates),
                "Default report template missing from API response",
                templates,
            )

            create_response = client.post(
                "/api/report-templates",
                headers=headers,
                json={
                    "template_key": "temp_report_template_verification",
                    "name": "Temp Report Template Verification",
                    "description": "Temporary template for report template verification.",
                    "applies_to": "maturity_report",
                    "sections_json": [
                        {"key": "summary", "title": "摘要", "required": True},
                        {"key": "delivery_readiness", "title": "交付就绪度", "required": True},
                    ],
                    "scoring_json": {
                        "total_score": 100,
                        "dimensions": [
                            {"key": "visibility", "name": "AI 可见度", "max_score": 20},
                            {"key": "custom_gap", "name": "模板专属未匹配维度", "max_score": 5},
                        ],
                    },
                    "delivery_checks_json": [
                        {"key": "sample_size", "label": "样本量", "required": 20},
                    ],
                    "status": "active",
                    "version": 99,
                },
            )
            create_response.raise_for_status()
            created_template = create_response.json()
            template_id = int(created_template["id"])

            company = Company(
                name="Temp Report Template Company",
                industry="GEO 报告模板",
                description="Temporary company for report template verification.",
                status="active",
            )
            db.add(company)
            db.flush()
            project = Project(
                company_id=company.id,
                name="Temp Report Template Project",
                target_industry="GEO SaaS",
                target_audience="市场负责人",
                status="active",
            )
            db.add(project)
            provider = LLMProvider(
                name="Temp Report Template Provider",
                provider_type="mock",
                model_name="mock-geo-search",
                auth_config={},
                status="active",
            )
            db.add(provider)
            db.flush()
            question = TargetQuestion(
                project_id=project.id,
                question_text="企业 GEO 成熟度报告模板应该包含哪些内容？",
                question_type="core",
                priority=5,
                status="active",
            )
            db.add(question)
            db.flush()
            task = CrawlTask(
                project_id=project.id,
                task_type="manual_batch",
                schedule_type="manual",
                provider_ids=[provider.id],
                target_question_ids=[question.id],
                status="success",
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
            )
            db.add(task)
            db.flush()
            result = CrawlResult(
                task_id=task.id,
                project_id=project.id,
                target_question_id=question.id,
                provider_id=provider.id,
                prompt_text=question.question_text,
                raw_answer=f"{company.name} 的报告模板需要包含证据、评分和交付检查。",
                answer_summary=f"{company.name} 被提及为报告模板样本。",
                status="success",
                collected_at=datetime.now(UTC),
            )
            db.add(result)
            db.flush()
            db.add(
                AnswerAnalysis(
                    crawl_result_id=result.id,
                    company_mentioned=True,
                    company_recommended=True,
                    company_rank=1,
                    sentiment="positive",
                    confidence=92,
                    analysis_json={},
                )
            )
            db.add(
                CitationSource(
                    crawl_result_id=result.id,
                    source_title="报告模板证据页",
                    source_url="https://example.com/report-template",
                    source_domain="example.com",
                    source_type="webpage",
                    is_owned=True,
                    is_placed=True,
                    crawlable_score=90,
                    ai_readiness_score=90,
                )
            )
            db.commit()

            report = generate_maturity_report(
                db,
                project,
                MaturityReportCreate(title="Temp Report Template Snapshot", report_period="verification"),
            )
            items = list(
                db.scalars(
                    select(MaturityScoreItem)
                    .where(MaturityScoreItem.report_id == report.id)
                    .order_by(MaturityScoreItem.id.asc())
                )
            )
            snapshot = (report.report_json or {}).get("report_template_snapshot") or {}
            score_alignment = (report.report_json or {}).get("template_score_alignment") or {}
            markdown = render_report_markdown(report, items)
            _require(snapshot.get("template_key") == "temp_report_template_verification", "Report template snapshot did not use active template", snapshot)
            _require(snapshot.get("version") == 99, "Report template snapshot version missing", snapshot)
            _require(score_alignment.get("template_dimension_count") == 2, "Template score alignment dimension count missing", score_alignment)
            _require(score_alignment.get("matched_dimension_count") == 1, "Template score alignment matched count wrong", score_alignment)
            _require(
                any(item.get("name") == "模板专属未匹配维度" for item in score_alignment.get("unmatched_template_dimensions") or []),
                "Template score alignment did not expose unmatched dimensions",
                score_alignment,
            )
            _require("报告模板：Temp Report Template Verification v99" in markdown, "Markdown missing report template line", markdown[:300])
            audit_count = db.scalar(
                select(AuditLog)
                .where(AuditLog.resource_type == "report_template")
                .where(AuditLog.resource_id == template_id)
            )
            _require(audit_count is not None, "Report template audit log missing", created_template)

            result_payload = {
                "ok": True,
                "verification_method": "FastAPI TestClient report template API plus report snapshot verification",
                "endpoint": "/api/report-templates",
                "default_template_key": default_template.template_key,
                "api_template_count": len(templates),
                "created_template_id": template_id,
                "report_id": report.id,
                "snapshot_template_key": snapshot.get("template_key"),
                "snapshot_version": snapshot.get("version"),
                "template_dimension_count": score_alignment.get("template_dimension_count"),
                "matched_dimension_count": score_alignment.get("matched_dimension_count"),
                "unmatched_template_dimension_count": len(score_alignment.get("unmatched_template_dimensions") or []),
                "markdown_has_template_line": True,
                "audit_log_created": True,
                "safety": {"temporary_data_cleaned": True},
            }
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return result_payload
        finally:
            if report is not None:
                db.execute(delete(MaturityScoreItem).where(MaturityScoreItem.report_id == report.id))
                db.execute(delete(MaturityReport).where(MaturityReport.id == report.id))
            if project is not None:
                result_ids = list(db.scalars(select(CrawlResult.id).where(CrawlResult.project_id == project.id)))
                if result_ids:
                    db.execute(delete(CitationSource).where(CitationSource.crawl_result_id.in_(result_ids)))
                    db.execute(delete(AnswerAnalysis).where(AnswerAnalysis.crawl_result_id.in_(result_ids)))
                    db.execute(delete(CrawlResult).where(CrawlResult.id.in_(result_ids)))
                db.execute(delete(CrawlTask).where(CrawlTask.project_id == project.id))
                db.execute(delete(TargetQuestion).where(TargetQuestion.project_id == project.id))
                db.execute(delete(Project).where(Project.id == project.id))
            if provider is not None:
                db.execute(delete(LLMProvider).where(LLMProvider.id == provider.id))
            if company is not None:
                db.execute(delete(Company).where(Company.id == company.id))
            if template_id is not None:
                db.execute(
                    delete(AuditLog)
                    .where(AuditLog.resource_type == "report_template")
                    .where(AuditLog.resource_id == template_id)
                )
                db.execute(delete(ReportTemplate).where(ReportTemplate.id == template_id))
            db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify report templates and maturity report template snapshots.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = verify_report_templates(output_path=args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
