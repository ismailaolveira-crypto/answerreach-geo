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
from app.models import AnswerAnalysis, Company, CrawlResult, CrawlTask, MaturityReport, MaturityScoreItem, Project
from app.schemas.report import MaturityReportCreate
from app.services.maturity_report import generate_maturity_report, render_report_markdown


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_analysis_correction_testclient.json"


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def verify_analysis_correction(
    *,
    output_path: Path,
    email: str = "geo-demo-e2e@example.com",
    password: str = "geo-demo-123",
) -> dict[str, Any]:
    Base.metadata.create_all(bind=engine)
    company: Company | None = None
    project: Project | None = None
    task: CrawlTask | None = None
    result: CrawlResult | None = None
    analysis: AnswerAnalysis | None = None
    report: MaturityReport | None = None

    with SessionLocal() as db:
        try:
            company = Company(
                name="Temp Analysis Correction Verification",
                industry="GEO 解析",
                status="active",
            )
            db.add(company)
            db.flush()
            project = Project(
                company_id=company.id,
                name="Temp Analysis Correction Project",
                target_industry="GEO SaaS",
                target_audience="运营负责人",
                status="active",
            )
            db.add(project)
            db.flush()
            task = CrawlTask(
                project_id=project.id,
                task_type="manual_batch",
                schedule_type="manual",
                status="success",
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
            )
            db.add(task)
            db.flush()
            result = CrawlResult(
                task_id=task.id,
                project_id=project.id,
                prompt_text="GEO 服务商是否被推荐？",
                raw_answer="该答案需要人工复核推荐关系。",
                answer_summary="自动解析先给出中性结果。",
                status="success",
                collected_at=datetime.now(UTC),
            )
            db.add(result)
            db.flush()
            analysis = AnswerAnalysis(
                crawl_result_id=result.id,
                company_mentioned=False,
                company_recommended=False,
                company_rank=None,
                sentiment="neutral",
                confidence=35,
                analysis_json={"method": "verification_seed"},
            )
            db.add(analysis)
            db.commit()

            client = TestClient(app)
            login = client.post("/api/auth/login", json={"email": email, "password": password})
            login.raise_for_status()
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            response = client.patch(
                f"/api/projects/{project.id}/crawl-results/{result.id}/analysis",
                headers=headers,
                json={
                    "company_mentioned": True,
                    "company_recommended": True,
                    "company_rank": 2,
                    "sentiment": "positive",
                    "confidence": 88,
                    "correction_note": "人工确认该答案列为推荐对象。",
                },
            )
            response.raise_for_status()
            payload = response.json()
            corrected = payload.get("analysis") or {}
            correction = (corrected.get("analysis_json") or {}).get("manual_correction") or {}
            _require(corrected.get("company_mentioned") is True, "company_mentioned was not corrected", corrected)
            _require(corrected.get("company_recommended") is True, "company_recommended was not corrected", corrected)
            _require(corrected.get("company_rank") == 2, "company_rank was not corrected", corrected)
            _require(corrected.get("sentiment") == "positive", "sentiment was not corrected", corrected)
            _require(corrected.get("confidence") == 88, "confidence was not corrected", corrected)
            _require(correction.get("previous", {}).get("confidence") == 35, "previous state was not captured", correction)
            _require(correction.get("note"), "correction note missing", correction)
            report = generate_maturity_report(
                db,
                project,
                MaturityReportCreate(title="Temp Analysis Correction Report", report_period="verification"),
            )
            report_json = report.report_json or {}
            evidence_quality = report_json.get("evidence_quality") or {}
            evidence_samples = report_json.get("evidence_samples") or []
            score_items = list(
                db.scalars(select(MaturityScoreItem).where(MaturityScoreItem.report_id == report.id))
            )
            markdown = render_report_markdown(report, score_items)
            _require(
                evidence_quality.get("manual_correction_count") == 1,
                "Manual correction count missing from report evidence quality",
                evidence_quality,
            )
            _require(
                evidence_quality.get("manual_correction_rate") == 1,
                "Manual correction rate missing from report evidence quality",
                evidence_quality,
            )
            _require(
                any(item.get("manual_corrected") for item in evidence_samples),
                "Manual correction flag missing from evidence samples",
                evidence_samples,
            )
            _require("人工校正样本数：1" in markdown, "Markdown does not expose manual correction count", markdown)
            _require("人工校正" in markdown, "Markdown does not mark corrected evidence sample", markdown)

            output = {
                "ok": True,
                "verification_method": "FastAPI TestClient answer analysis correction plus maturity report evidence",
                "project_id": project.id,
                "crawl_result_id": result.id,
                "report_id": report.id,
                "analysis": {
                    "company_mentioned": corrected.get("company_mentioned"),
                    "company_recommended": corrected.get("company_recommended"),
                    "company_rank": corrected.get("company_rank"),
                    "sentiment": corrected.get("sentiment"),
                    "confidence": corrected.get("confidence"),
                    "has_manual_correction": bool(correction),
                },
                "report_evidence": {
                    "manual_correction_count": evidence_quality.get("manual_correction_count"),
                    "manual_correction_rate": evidence_quality.get("manual_correction_rate"),
                    "manual_corrected_sample_count": sum(1 for item in evidence_samples if item.get("manual_corrected")),
                    "markdown_has_manual_correction": "人工校正样本数：1" in markdown,
                },
                "safety": {"temporary_data_cleaned": True},
            }
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
            return output
        finally:
            if report is not None:
                db.execute(delete(MaturityScoreItem).where(MaturityScoreItem.report_id == report.id))
                db.execute(delete(MaturityReport).where(MaturityReport.id == report.id))
            if analysis is not None:
                db.execute(delete(AnswerAnalysis).where(AnswerAnalysis.id == analysis.id))
            if result is not None:
                db.execute(delete(CrawlResult).where(CrawlResult.id == result.id))
            if task is not None:
                db.execute(delete(CrawlTask).where(CrawlTask.id == task.id))
            if project is not None:
                db.execute(delete(Project).where(Project.id == project.id))
            if company is not None:
                db.execute(delete(Company).where(Company.id == company.id))
            db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify manual answer analysis correction.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = verify_analysis_correction(output_path=args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
