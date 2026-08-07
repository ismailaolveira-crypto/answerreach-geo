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
    ContentAsset,
    CrawlResult,
    CrawlTask,
    LLMProvider,
    MentionedEntity,
    PlacementRecord,
    Project,
    UsageRecord,
)
from app.services.answer_parser import analyze_answer


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_source_intelligence_testclient.json"


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def _cleanup_project(db, project_id: int) -> None:
    result_ids = list(db.scalars(select(CrawlResult.id).where(CrawlResult.project_id == project_id)))
    task_ids = list(db.scalars(select(CrawlTask.id).where(CrawlTask.project_id == project_id)))
    if result_ids:
        db.execute(delete(UsageRecord).where(UsageRecord.crawl_result_id.in_(result_ids)))
        db.execute(delete(AnswerAnalysis).where(AnswerAnalysis.crawl_result_id.in_(result_ids)))
        db.execute(delete(MentionedEntity).where(MentionedEntity.crawl_result_id.in_(result_ids)))
        db.execute(delete(CitationSource).where(CitationSource.crawl_result_id.in_(result_ids)))
        db.execute(delete(CrawlResult).where(CrawlResult.id.in_(result_ids)))
    if task_ids:
        db.execute(delete(UsageRecord).where(UsageRecord.task_id.in_(task_ids)))
        db.execute(delete(CrawlTask).where(CrawlTask.id.in_(task_ids)))
    db.execute(delete(PlacementRecord).where(PlacementRecord.project_id == project_id))
    db.execute(delete(ContentAsset).where(ContentAsset.project_id == project_id))
    db.commit()


def verify_source_intelligence(
    *,
    output_path: Path,
    email: str = "geo-demo-e2e@example.com",
    password: str = "geo-demo-123",
) -> dict[str, Any]:
    Base.metadata.create_all(bind=engine)
    company: Company | None = None
    project: Project | None = None
    provider: LLMProvider | None = None
    task: CrawlTask | None = None
    result: CrawlResult | None = None
    source_url = "https://example.com/faq/geo-source-intelligence"

    with SessionLocal() as db:
        try:
            company = Company(
                name="Temp Source Intelligence Verification",
                industry="GEO 信源",
                website_url="https://example.com",
                description="Temporary company for source intelligence verification.",
                status="active",
            )
            db.add(company)
            db.flush()
            project = Project(
                company_id=company.id,
                name="Temp Source Intelligence Project",
                target_industry="GEO SaaS",
                target_audience="内容运营",
                status="active",
            )
            db.add(project)
            db.flush()
            _cleanup_project(db, project.id)
            provider = LLMProvider(
                name="Temp Source Intelligence Provider",
                provider_type="mock",
                model_name="mock-geo-search",
                auth_config={},
                status="active",
            )
            db.add(provider)
            db.flush()
            asset = ContentAsset(
                company_id=company.id,
                project_id=project.id,
                title="GEO 信源 FAQ",
                content_type="faq",
                source_url=source_url,
                body_text="结构化 FAQ，适合 AI 摘录。",
                publish_channel="官网 FAQ",
                status="approved",
            )
            placement = PlacementRecord(
                project_id=project.id,
                content_asset_id=None,
                channel="官网 FAQ",
                target_url=source_url,
                planned_at=datetime.now(UTC),
                published_at=datetime.now(UTC),
                status="published",
                visibility="customer_visible",
                delivery_status="ready",
                notes="已投放到可抓取 FAQ 页面。",
            )
            db.add_all([asset, placement])
            db.flush()
            task = CrawlTask(
                project_id=project.id,
                task_type="manual_batch",
                schedule_type="manual",
                provider_ids=[provider.id],
                status="success",
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
            )
            db.add(task)
            db.flush()
            result = CrawlResult(
                task_id=task.id,
                project_id=project.id,
                provider_id=provider.id,
                prompt_text="GEO 信源应该怎么建设？",
                raw_answer=(
                    f"推荐关注 {company.name}，其 FAQ 页面可作为候选信源：{source_url}。"
                    "这个页面结构清晰，适合 AI 摘录。"
                ),
                answer_summary=f"{company.name} 被推荐，且引用了已投放 FAQ 信源。",
                status="success",
                collected_at=datetime.now(UTC),
            )
            db.add(result)
            db.flush()
            analyze_answer(db, result, company, [])
            db.commit()

            client = TestClient(app)
            login = client.post("/api/auth/login", json={"email": email, "password": password})
            login.raise_for_status()
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            response = client.get(f"/api/projects/{project.id}/source-insights", headers=headers)
            response.raise_for_status()
            insights = response.json()
            insight = next((item for item in insights if item.get("source_url") == source_url), None)
            _require(insight is not None, "Source insight missing created source", insights)
            _require(insight.get("is_placed") is True, "Source insight did not mark placed", insight)
            _require(insight.get("has_content_asset") is True, "Source insight did not mark content asset", insight)
            _require(int(insight.get("placement_count") or 0) == 1, "Placement count mismatch", insight)
            _require(int(insight.get("published_placement_count") or 0) == 1, "Published placement count mismatch", insight)
            _require(insight.get("ai_readiness_status") == "excellent", "AI readiness status mismatch", insight)
            detail_response = client.get(
                f"/api/projects/{project.id}/source-insights/detail",
                params={"source_url": source_url},
                headers=headers,
            )
            detail_response.raise_for_status()
            detail = detail_response.json()
            _require(
                detail["insight"].get("placement_frequency_label") == "单次投放",
                "Placement frequency label mismatch",
                detail,
            )

            output = {
                "ok": True,
                "verification_method": "FastAPI TestClient source insight verification",
                "project_id": project.id,
                "source_url": source_url,
                "insight": {
                    "is_placed": insight.get("is_placed"),
                    "has_content_asset": insight.get("has_content_asset"),
                    "placement_count": insight.get("placement_count"),
                    "published_placement_count": insight.get("published_placement_count"),
                    "placement_frequency_label": insight.get("placement_frequency_label"),
                    "ai_readiness_score": insight.get("ai_readiness_score"),
                    "ai_readiness_status": insight.get("ai_readiness_status"),
                    "crawlable_score": insight.get("crawlable_score"),
                    "crawlability_status": insight.get("crawlability_status"),
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
            if provider is not None:
                db.execute(delete(LLMProvider).where(LLMProvider.id == provider.id))
            if company is not None:
                db.execute(delete(Company).where(Company.id == company.id))
            db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify source placement frequency and AI readiness insight.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = verify_source_intelligence(output_path=args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
