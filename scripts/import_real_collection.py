import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import (
    Company,
    Competitor,
    CrawlResult,
    CrawlTask,
    CrawlTaskLog,
    LLMProvider,
    LLMProviderTestRun,
    Project,
)
from app.services.answer_parser import analyze_answer
from app.services.usage import record_usage


def _read_answer(response_path: Path) -> str:
    data = json.loads(response_path.read_text())
    if "error" in data:
        raise ValueError(f"{response_path} returned error: {data['error']}")
    return data["choices"][0]["message"]["content"]


def import_collection(project_id: int, collection_dir: Path) -> dict:
    metas = sorted(collection_dir.glob("provider-*_question-*.meta.json"))
    if not metas:
        raise ValueError(f"No meta files found in {collection_dir}")

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        if project is None:
            raise ValueError(f"Project {project_id} not found")
        company = db.get(Company, project.company_id)
        if company is None:
            raise ValueError(f"Company for project {project_id} not found")
        competitors = list(db.scalars(select(Competitor).where(Competitor.project_id == project.id)))

        provider_ids = sorted({json.loads(path.read_text())["provider_id"] for path in metas})
        question_ids = sorted({json.loads(path.read_text())["target_question_id"] for path in metas})
        task = CrawlTask(
            project_id=project.id,
            task_type="real_api_curl_import",
            schedule_type="manual",
            provider_ids=provider_ids,
            target_question_ids=question_ids,
            keyword_ids=[],
            status="running",
            started_at=datetime.now(UTC),
        )
        db.add(task)
        db.flush()
        db.add(
            CrawlTaskLog(
                task_id=task.id,
                project_id=project.id,
                level="info",
                message="Imported real API collection responses",
                detail_json={"collection_dir": str(collection_dir), "provider_ids": provider_ids},
            )
        )

        imported = []
        skipped = []
        for meta_path in metas:
            meta = json.loads(meta_path.read_text())
            response_path = Path(str(meta_path).replace(".meta.json", ".response.json"))
            if str(meta.get("http_code")) != "200":
                skipped.append(
                    {
                        "meta_path": str(meta_path),
                        "response_path": str(response_path),
                        "http_code": meta.get("http_code"),
                    }
                )
                continue
            raw_answer = _read_answer(response_path)
            if not raw_answer.strip():
                skipped.append(
                    {
                        "meta_path": str(meta_path),
                        "response_path": str(response_path),
                        "http_code": meta.get("http_code"),
                        "reason": "empty_answer",
                    }
                )
                continue
            provider = db.get(LLMProvider, meta["provider_id"])
            if provider is None:
                raise ValueError(f"Provider {meta['provider_id']} not found")
            result = CrawlResult(
                task_id=task.id,
                project_id=project.id,
                target_question_id=meta["target_question_id"],
                keyword_id=None,
                provider_id=provider.id,
                prompt_text=meta["question_text"],
                raw_answer=raw_answer,
                answer_summary=raw_answer[:180],
                status="success",
                collected_at=datetime.now(UTC),
            )
            db.add(result)
            db.flush()
            record_usage(
                db,
                provider=provider,
                action="crawl.answer",
                prompt_text=meta["question_text"],
                completion_text=raw_answer,
                company_id=company.id,
                project_id=project.id,
                task_id=task.id,
                crawl_result_id=result.id,
                detail={"import_method": "real_api_curl_import", "response_path": str(response_path)},
            )
            analyze_answer(db, result, company, competitors)
            imported.append({"result_id": result.id, **meta})

        for provider_id in provider_ids:
            provider_results = [item for item in imported if item["provider_id"] == provider_id]
            if not provider_results:
                db.add(
                    LLMProviderTestRun(
                        provider_id=provider_id,
                        ok=False,
                        prompt_text="real_api_curl_import",
                        company_name=company.name,
                        industry=project.target_industry or company.industry,
                        error_message="No successful HTTP 200 response was imported for this provider.",
                        latency_ms=None,
                    )
                )
                continue
            latest = provider_results[-1]
            latest_answer = db.get(CrawlResult, latest["result_id"])
            db.add(
                LLMProviderTestRun(
                    provider_id=provider_id,
                    ok=True,
                    prompt_text=latest["question_text"],
                    company_name=company.name,
                    industry=project.target_industry or company.industry,
                    answer_summary=(latest_answer.answer_summary if latest_answer else "")[:180],
                    raw_answer_preview=(latest_answer.raw_answer if latest_answer else "")[:1000],
                    latency_ms=None,
                )
            )

        task.status = "success" if imported else "failed"
        task.error_message = None if imported else "No successful responses were imported from this collection."
        task.finished_at = datetime.now(UTC)
        db.add(
            CrawlTaskLog(
                task_id=task.id,
                project_id=project.id,
                level="info" if imported else "error",
                message="Real API collection import completed",
                detail_json={"result_count": len(imported), "skipped_count": len(skipped), "skipped": skipped[:20]},
            )
        )
        db.commit()
        return {
            "task_id": task.id,
            "result_count": len(imported),
            "skipped_count": len(skipped),
            "provider_ids": provider_ids,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", type=int, default=1)
    parser.add_argument("--collection-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(import_collection(args.project_id, args.collection_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
