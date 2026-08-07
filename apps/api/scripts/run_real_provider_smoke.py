import argparse
import json
import sys
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.models import CrawlResult, CrawlTask, CrawlTaskLog, Keyword, LLMProvider, TargetQuestion, UsageRecord
from app.schemas.search import CrawlTaskCreate
from app.services.crawl_runner import KEYWORD_PROMPT_VARIANT_COUNT, run_crawl_task
from app.services.llm_provider import diagnose_provider


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_real_provider_smoke.json"


def _parse_ids(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _provider_summary(provider: LLMProvider) -> dict[str, Any]:
    diagnostic = diagnose_provider(provider)
    return {
        "id": provider.id,
        "name": provider.name,
        "provider_type": provider.provider_type,
        "model_name": provider.model_name,
        "status": provider.status,
        "ready": diagnostic["ready"],
        "auth_ready": diagnostic["auth_ready"],
        "search_mode": diagnostic["search_mode"],
        "search_access_status": diagnostic["search_access_status"],
        "base_url": diagnostic["base_url"],
        "missing": diagnostic["missing"],
        "warnings": diagnostic["warnings"],
    }


def _collect_scope(db, project_id: int, question_limit: int, keyword_limit: int) -> tuple[list[int], list[int]]:
    question_ids = list(
        db.scalars(
            select(TargetQuestion.id)
            .where(TargetQuestion.project_id == project_id)
            .order_by(TargetQuestion.priority, TargetQuestion.id)
            .limit(question_limit)
        )
    )
    keyword_ids = list(
        db.scalars(
            select(Keyword.id)
            .where(Keyword.project_id == project_id)
            .order_by(Keyword.priority, Keyword.id)
            .limit(keyword_limit)
        )
    )
    return question_ids, keyword_ids


def _latest_task_logs(db, task_id: int, limit: int = 8) -> list[dict[str, Any]]:
    logs = list(
        db.scalars(
            select(CrawlTaskLog)
            .where(CrawlTaskLog.task_id == task_id)
            .order_by(CrawlTaskLog.id.desc())
            .limit(limit)
        )
    )
    return [
        {
            "level": item.level,
            "message": item.message,
            "detail": item.detail_json,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in reversed(logs)
    ]


def run_smoke(
    *,
    project_id: int,
    provider_ids: list[int],
    question_limit: int,
    keyword_limit: int,
    dry_run: bool,
    output_path: Path,
) -> dict[str, Any]:
    db = SessionLocal()
    try:
        providers = list(db.scalars(select(LLMProvider).where(LLMProvider.id.in_(provider_ids)).order_by(LLMProvider.id)))
        provider_map = {provider.id: provider for provider in providers}
        missing_provider_ids = [provider_id for provider_id in provider_ids if provider_id not in provider_map]
        question_ids, keyword_ids = _collect_scope(db, project_id, question_limit, keyword_limit)
        provider_summaries = [_provider_summary(provider_map[provider_id]) for provider_id in provider_ids if provider_id in provider_map]
        planned_call_count = len(provider_summaries) * (
            len(question_ids) + len(keyword_ids) * KEYWORD_PROMPT_VARIANT_COUNT
        )
        base_result: dict[str, Any] = {
            "ok": False,
            "verification_method": "direct SQLAlchemy smoke runner",
            "project_id": project_id,
            "provider_ids": provider_ids,
            "missing_provider_ids": missing_provider_ids,
            "question_ids": question_ids,
            "keyword_ids": keyword_ids,
            "planned_call_count": planned_call_count,
            "providers": provider_summaries,
            "dry_run": dry_run,
            "created_at": datetime.now(UTC).isoformat(),
            "safety": {
                "raw_answers_printed": False,
                "api_keys_printed": False,
            },
        }
        if missing_provider_ids:
            base_result["error"] = f"Provider IDs not found: {missing_provider_ids}"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(base_result, ensure_ascii=False, indent=2), encoding="utf-8")
            return base_result
        if planned_call_count <= 0:
            base_result["error"] = "No questions or keywords selected for smoke run."
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(base_result, ensure_ascii=False, indent=2), encoding="utf-8")
            return base_result
        if dry_run:
            base_result["ok"] = True
            base_result["status"] = "planned"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(base_result, ensure_ascii=False, indent=2), encoding="utf-8")
            return base_result

        task = CrawlTask(
            project_id=project_id,
            task_type="real_provider_smoke",
            schedule_type="manual",
            provider_ids=provider_ids,
            target_question_ids=question_ids,
            keyword_ids=keyword_ids,
            status="pending",
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        payload = CrawlTaskCreate(
            provider_ids=provider_ids,
            target_question_ids=question_ids,
            keyword_ids=keyword_ids,
            execute_now=True,
        )
        run_crawl_task(db, task, payload)
        db.refresh(task)
        result_count = int(db.scalar(select(func.count(CrawlResult.id)).where(CrawlResult.task_id == task.id)) or 0)
        usage = db.execute(
            select(
                func.count(UsageRecord.id),
                func.coalesce(func.sum(UsageRecord.total_tokens), 0),
                func.coalesce(func.sum(UsageRecord.estimated_cost), 0.0),
            ).where(UsageRecord.task_id == task.id)
        ).one()
        base_result.update(
            {
                "ok": task.status == "success" and result_count == planned_call_count,
                "task_id": task.id,
                "status": task.status,
                "error_message": task.error_message,
                "result_count": result_count,
                "usage_record_count": int(usage[0] or 0),
                "total_tokens": int(usage[1] or 0),
                "estimated_cost": float(usage[2] or 0.0),
                "logs": _latest_task_logs(db, task.id),
            }
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(base_result, ensure_ascii=False, indent=2), encoding="utf-8")
        return base_result
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a tiny real-provider GEO crawl smoke test.")
    parser.add_argument("--project-id", type=int, default=9)
    parser.add_argument("--provider-ids", default="9,12")
    parser.add_argument("--question-limit", type=int, default=1)
    parser.add_argument("--keyword-limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run_smoke(
        project_id=args.project_id,
        provider_ids=_parse_ids(args.provider_ids),
        question_limit=args.question_limit,
        keyword_limit=args.keyword_limit,
        dry_run=args.dry_run,
        output_path=args.output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
