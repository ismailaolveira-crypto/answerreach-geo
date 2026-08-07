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
    UsageRecord,
)
from app.schemas.report import MaturityReportCreate
from app.services.maturity_report import generate_maturity_report, render_report_markdown


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_browser_observation_evidence_testclient.json"
PLATFORMS = [
    ("豆包", "https://www.doubao.com/chat"),
    ("DeepSeek", "https://chat.deepseek.com/"),
    ("Kimi", "https://www.kimi.com/"),
    ("千问", "https://www.qianwen.com/"),
]


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def _cleanup_project(db, project_id: int) -> None:
    result_ids = list(db.scalars(select(CrawlResult.id).where(CrawlResult.project_id == project_id)))
    task_ids = list(db.scalars(select(CrawlTask.id).where(CrawlTask.project_id == project_id)))
    if result_ids:
        db.execute(delete(UsageRecord).where(UsageRecord.crawl_result_id.in_(result_ids)))
        db.execute(delete(CitationSource).where(CitationSource.crawl_result_id.in_(result_ids)))
        db.execute(delete(MentionedEntity).where(MentionedEntity.crawl_result_id.in_(result_ids)))
        db.execute(delete(AnswerAnalysis).where(AnswerAnalysis.crawl_result_id.in_(result_ids)))
        db.execute(delete(CrawlResult).where(CrawlResult.id.in_(result_ids)))
    if task_ids:
        db.execute(delete(UsageRecord).where(UsageRecord.task_id.in_(task_ids)))
        db.execute(delete(CrawlTask).where(CrawlTask.id.in_(task_ids)))
    db.execute(delete(MaturityReport).where(MaturityReport.project_id == project_id))
    db.execute(delete(TargetQuestion).where(TargetQuestion.project_id == project_id))
    db.execute(delete(Keyword).where(Keyword.project_id == project_id))
    db.commit()


def verify_browser_observation_evidence(
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
                name="Temp Browser Observation Verification",
                industry="GEO 观测",
                website_url="https://example.com",
                status="active",
            )
            db.add(company)
            db.flush()
            project = Project(
                company_id=company.id,
                name="Temp Browser Observation Project",
                target_industry="GEO SaaS",
                target_audience="内容运营",
                status="active",
            )
            db.add(project)
            db.flush()
            _cleanup_project(db, project.id)
            providers = [
                LLMProvider(
                    name=f"Temp {platform} Browser Observation Provider",
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
                question_text="GEO 优化服务商怎么选？",
                priority=1,
                status="active",
            )
            keyword = Keyword(
                project_id=project.id,
                keyword="GEO 优化",
                priority=1,
                status="active",
            )
            report = MaturityReport(
                project_id=project.id,
                title="Temp Browser Observation Report",
                report_period="verification",
                total_score=42,
                maturity_level="L2",
                summary="Temporary report for browser observation binding.",
                report_json={},
                status="generated",
                generated_at=datetime.now(UTC),
            )
            db.add_all([*providers, question, keyword, report])
            db.commit()
            for provider in providers:
                db.refresh(provider)
            db.refresh(question)
            db.refresh(keyword)
            db.refresh(report)

            client = TestClient(app)
            login = client.post("/api/auth/login", json={"email": email, "password": password})
            login.raise_for_status()
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            bulk_payload = {
                "observations": [
                    {
                        "provider_id": provider.id,
                        "report_id": report.id,
                        "target_question_id": question.id,
                        "keyword_id": keyword.id,
                        "platform_name": platform,
                        "prompt_text": question.question_text,
                        "raw_answer": (
                            f"{platform} 网页端回答推荐关注 {company.name}。参考来源包括 "
                            "https://example.com/geo-guide 和 https://media.example.com/geo-ranking。"
                        ),
                        "answer_summary": f"{platform} 网页端答案提到 {company.name} 并给出来源。",
                        "source_urls": [
                            "https://example.com/geo-guide",
                            "https://media.example.com/geo-ranking",
                        ],
                        "screenshot_url": f"file:///tmp/browser-observation-evidence-{platform}.png",
                        "observation_url": url,
                        "observer_name": "验收脚本",
                        "note": f"{platform} 网页端人工观测样本。",
                    }
                    for provider, (platform, url) in zip(providers, PLATFORMS, strict=True)
                ]
            }
            response = client.post(
                f"/api/projects/{project.id}/browser-observations/bulk",
                headers=headers,
                json=bulk_payload,
            )
            response.raise_for_status()
            bulk_detail = response.json()
            result_ids = bulk_detail["result_ids"]
            _require(bulk_detail.get("created_count") == 4, "Bulk created count mismatch", bulk_detail)
            _require(bulk_detail.get("screenshot_evidence_count") == 4, "Bulk screenshot count mismatch", bulk_detail)
            _require(bulk_detail.get("source_count", 0) >= 16, "Bulk source count mismatch", bulk_detail)
            for detail, provider in zip(bulk_detail.get("results") or [], providers, strict=True):
                _require(detail.get("provider_id") == provider.id, "Provider binding mismatch", detail)
                _require(detail.get("analysis"), "Answer analysis missing", detail)
                citation_sources = detail.get("citation_sources") or []
                source_types = [item.get("source_type") for item in citation_sources]
                _require(len(citation_sources) >= 4, "Citation source count mismatch", detail)
                _require("web" in source_types, "Parsed web source missing", citation_sources)
                _require("browser_observation" in source_types, "Browser observation source missing", citation_sources)
                _require("screenshot" in source_types, "Screenshot source missing", citation_sources)

            list_response = client.get(f"/api/projects/{project.id}/browser-observations", headers=headers)
            list_response.raise_for_status()
            observations = list_response.json()
            listed_observations = [item for item in observations if item.get("id") in result_ids]
            _require(len(listed_observations) == 4, "Observation list count mismatch", observations)
            _require(
                {item.get("platform_name") for item in listed_observations} == {platform for platform, _ in PLATFORMS},
                "Observation platform coverage mismatch",
                listed_observations,
            )
            for observation in listed_observations:
                _require(observation.get("report_id") == report.id, "Report binding mismatch", observation)
                _require(int(observation.get("source_count") or 0) >= 4, "Observation source count mismatch", observation)
                _require(
                    observation.get("screenshot_evidence_count") == 1,
                    "Screenshot evidence count mismatch",
                    observation,
                )

            db.expire_all()
            generated_report = generate_maturity_report(
                db,
                project,
                MaturityReportCreate(title="Temp Generated Browser Observation Evidence Report"),
            )
            evidence_quality = generated_report.report_json["evidence_quality"]
            _require(
                evidence_quality.get("browser_observation_count") == 4,
                "Report evidence did not count browser observation",
                evidence_quality,
            )
            _require(
                evidence_quality.get("screenshot_evidence_count") == 4,
                "Report evidence did not count screenshot",
                evidence_quality,
            )
            _require(
                evidence_quality.get("browser_observation_platform_count") == 4,
                "Report evidence did not count browser observation platform",
                evidence_quality,
            )
            _require(
                set(evidence_quality.get("browser_observation_platforms") or []) == {platform for platform, _ in PLATFORMS},
                "Report evidence did not preserve browser observation platform name",
                evidence_quality,
            )
            items = list(
                db.scalars(
                    select(MaturityScoreItem)
                    .where(MaturityScoreItem.report_id == generated_report.id)
                    .order_by(MaturityScoreItem.id.asc())
                )
            )
            markdown = render_report_markdown(generated_report, items)
            _require("网页端覆盖平台数：4" in markdown, "Markdown missing browser platform count", markdown)
            for platform, _ in PLATFORMS:
                _require(platform in markdown, "Markdown missing browser platform name", markdown)

            readiness_response = client.get(f"/api/projects/{project.id}/operational-readiness", headers=headers)
            readiness_response.raise_for_status()
            readiness = readiness_response.json()
            evidence_check = next(
                (item for item in readiness.get("checks", []) if item.get("key") == "browser_observation_evidence"),
                None,
            )
            _require(evidence_check and evidence_check.get("ok"), "Operational readiness evidence check failed", readiness)

            output = {
                "ok": True,
                "verification_method": "FastAPI TestClient browser observation evidence verification",
                "project_id": project.id,
                "result_ids": result_ids,
                "observation": {
                    "platforms": sorted(item.get("platform_name") for item in listed_observations),
                    "source_count": sum(int(item.get("source_count") or 0) for item in listed_observations),
                    "screenshot_evidence_count": sum(
                        int(item.get("screenshot_evidence_count") or 0) for item in listed_observations
                    ),
                },
                "evidence_quality": {
                    "browser_observation_count": evidence_quality.get("browser_observation_count"),
                    "browser_observation_platform_count": evidence_quality.get(
                        "browser_observation_platform_count"
                    ),
                    "browser_observation_platforms": evidence_quality.get("browser_observation_platforms"),
                    "screenshot_evidence_count": evidence_quality.get("screenshot_evidence_count"),
                    "browser_observation_rate": evidence_quality.get("browser_observation_rate"),
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
    parser = argparse.ArgumentParser(description="Verify manual browser observation evidence enters report quality.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = verify_browser_observation_evidence(output_path=args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
