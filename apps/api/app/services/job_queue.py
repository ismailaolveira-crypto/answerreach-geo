from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import (
    CrawlTask,
    CrawlTaskLog,
    GeoObservationBatch,
    GeoObservationTask,
    QueueJob,
)
from app.schemas.search import CrawlTaskCreate
from app.services.crawl_runner import run_crawl_task


TRANSIENT_ERROR_MARKERS = (
    "timeout",
    "timed out",
    "connection reset",
    "connection aborted",
    "connection refused",
    "handshake operation",
    "temporarily unavailable",
    "too many requests",
    "http 429",
    "http 502",
    "http 503",
    "http 504",
)


def is_transient_job_error(exc: Exception) -> bool:
    """Return True only for failures that can plausibly succeed unchanged later."""

    detail = getattr(exc, "detail", None)
    message = str(detail or exc).lower()
    return any(marker in message for marker in TRANSIENT_ERROR_MARKERS)


def retry_delay_seconds(attempts: int) -> int:
    """Short exponential backoff keeps the UI moving without hammering providers."""

    return min(30, 3 * (2 ** max(0, attempts - 1)))


def sync_observation_task_from_job(db: Session, job: QueueJob) -> None:
    """Mirror queue execution into the canonical observation ledger."""

    payload = dict(job.payload_json or {})
    task_id = int(payload.get("observation_task_id") or 0)
    if not task_id:
        return
    task = db.get(GeoObservationTask, task_id)
    if task is None:
        return
    task.status = "completed" if job.status == "success" else job.status
    task.attempt_count = job.attempts
    task.run_id = int(payload["run_id"]) if payload.get("run_id") else task.run_id
    task.evidence_id = (
        int(payload["evidence_id"]) if payload.get("evidence_id") else task.evidence_id
    )
    task.error_detail = job.error_message
    task.started_at = job.started_at
    task.completed_at = job.finished_at if job.status in {"success", "failed"} else None
    db.add(task)
    batch = db.get(GeoObservationBatch, task.batch_id)
    if batch is not None:
        completed = int(
            db.scalar(
                select(func.count())
                .select_from(GeoObservationTask)
                .where(
                    GeoObservationTask.batch_id == batch.id,
                    GeoObservationTask.status == "completed",
                )
            )
            or 0
        )
        failed = int(
            db.scalar(
                select(func.count())
                .select_from(GeoObservationTask)
                .where(
                    GeoObservationTask.batch_id == batch.id,
                    GeoObservationTask.status == "failed",
                )
            )
            or 0
        )
        running = int(
            db.scalar(
                select(func.count())
                .select_from(GeoObservationTask)
                .where(
                    GeoObservationTask.batch_id == batch.id,
                    GeoObservationTask.status == "running",
                )
            )
            or 0
        )
        batch.completed_tasks = completed
        batch.failed_tasks = failed
        if completed + failed >= batch.total_tasks and batch.total_tasks > 0:
            batch.status = "completed" if failed == 0 else "partial"
            batch.completed_at = job.finished_at or datetime.now(UTC)
        elif completed or failed or running:
            batch.status = "running"
            batch.started_at = batch.started_at or job.started_at or datetime.now(UTC)
            batch.completed_at = None
        else:
            batch.status = "pending"
        db.add(batch)


def enqueue_crawl_task_job(
    db: Session,
    *,
    task: CrawlTask,
    schedule_id: int | None = None,
    target_question_ids: list[int] | None = None,
    keyword_ids: list[int] | None = None,
    scheduled_at: datetime | None = None,
) -> QueueJob:
    job = QueueJob(
        job_type="crawl_task.run",
        status="pending",
        priority=0,
        scheduled_at=scheduled_at or datetime.now(UTC),
        payload_json={
            "task_id": task.id,
            "project_id": task.project_id,
            "schedule_id": schedule_id,
            "provider_ids": task.provider_ids,
            "target_question_ids": target_question_ids or [],
            "keyword_ids": keyword_ids or [],
        },
    )
    db.add(job)
    db.flush()
    db.add(
        CrawlTaskLog(
            task_id=task.id,
            project_id=task.project_id,
            level="info",
            message="Crawl task enqueued",
            detail_json={"queue_job_id": job.id, "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None},
        )
    )
    db.flush()
    return job


def claim_next_job(
    db: Session,
    now: datetime | None = None,
    project_id: int | None = None,
    project_ids: list[int] | None = None,
) -> QueueJob | None:
    checked_at = now or datetime.now(UTC)
    stmt = (
        select(QueueJob)
        .where(QueueJob.status == "pending")
        .where(QueueJob.scheduled_at <= checked_at)
    )
    if project_id is not None:
        stmt = stmt.where(QueueJob.payload_json["project_id"].as_integer() == project_id)
    elif project_ids is not None:
        if not project_ids:
            return None
        stmt = stmt.where(QueueJob.payload_json["project_id"].as_integer().in_(project_ids))
    # Compare-and-swap prevents concurrent workers from claiming the same job.
    # This lets observation batches run with bounded concurrency without
    # duplicating paid model calls.
    for _ in range(5):
        job_id = db.scalar(stmt.with_only_columns(QueueJob.id).order_by(QueueJob.priority.desc(), QueueJob.created_at.asc()).limit(1))
        if job_id is None:
            return None
        claimed = db.execute(
            update(QueueJob)
            .where(QueueJob.id == job_id, QueueJob.status == "pending")
            .values(status="running", started_at=checked_at, attempts=QueueJob.attempts + 1)
        )
        db.commit()
        if claimed.rowcount == 1:
            job = db.get(QueueJob, job_id)
            if job is not None:
                sync_observation_task_from_job(db, job)
                db.commit()
                db.refresh(job)
            return job
    return None


def run_job(db: Session, job: QueueJob) -> QueueJob:
    try:
        if job.job_type == "crawl_task.run":
            task_id = int(job.payload_json["task_id"])
            task = db.get(CrawlTask, task_id)
            if task is None:
                raise ValueError(f"Crawl task not found: {task_id}")
            payload = CrawlTaskCreate(
                task_type=task.task_type,
                schedule_type=task.schedule_type,
                provider_ids=list(job.payload_json.get("provider_ids") or task.provider_ids),
                target_question_ids=list(job.payload_json.get("target_question_ids") or task.target_question_ids),
                keyword_ids=list(job.payload_json.get("keyword_ids") or task.keyword_ids),
                execute_now=False,
            )
            run_crawl_task(db, task, payload)
            job.status = "success" if task.status == "success" else "failed"
            job.error_message = task.error_message
        elif job.job_type == "geo_observation.collect":
            # Local import avoids coupling the generic queue module to the v1 route at startup.
            from app.models import User
            from app.v1.routes import observe_provider_web_search
            from app.v1.schemas import OfficialApiObservationRequest

            payload_json = dict(job.payload_json or {})
            user = db.get(User, int(payload_json["actor_user_id"]))
            if user is None:
                raise ValueError("Observation job actor no longer exists")
            db.info["geo_observation_task_id"] = int(
                payload_json.get("observation_task_id") or 0
            )
            try:
                result = observe_provider_web_search(
                    int(payload_json["workspace_id"]),
                    OfficialApiObservationRequest(
                        question_plan_id=int(payload_json["question_plan_id"]),
                        provider_id=int(payload_json["provider_id"]),
                        repeat_index=int(payload_json.get("repeat_index") or 1),
                        repeat_count=int(payload_json.get("repeat_count") or 1),
                        observation_group_id=payload_json.get("observation_group_id"),
                    ),
                    db,
                    user,
                )
            finally:
                db.info.pop("geo_observation_task_id", None)
            job.payload_json = {
                **payload_json,
                "run_id": result["run"].id,
                "evidence_id": result["evidence"].id,
            }
            job.status = "success"
            job.error_message = None
        elif job.job_type == "llm_provider.test":
            # Provider tests can take tens of seconds because the model must
            # execute a real web search. Run them durably in the worker so the
            # configuration page never blocks the user's navigation.
            from app.api.routes.providers import test_provider
            from app.models import User
            from app.schemas.search import LLMProviderTestRequest

            payload_json = dict(job.payload_json or {})
            user = db.get(User, int(payload_json["actor_user_id"]))
            if user is None:
                raise ValueError("Provider test job actor no longer exists")
            job.payload_json = {**payload_json, "stage": "testing"}
            db.add(job)
            db.commit()
            db.refresh(job)
            result = test_provider(
                int(payload_json["provider_id"]),
                LLMProviderTestRequest(
                    prompt_text=str(payload_json.get("prompt_text") or "企业级大模型治理平台怎么选？"),
                    company_name=str(payload_json.get("company_name") or "示例企业"),
                    industry=str(payload_json.get("industry") or "网络安全"),
                ),
                db,
                user,
            )
            job.payload_json = {
                **payload_json,
                "stage": "complete",
                "test_run_id": result.id,
                "test_ok": result.ok,
                "latency_ms": result.latency_ms,
                "answer_summary": result.answer_summary,
                "error_message": result.error_message,
            }
            job.status = "success"
            job.error_message = None
        elif job.job_type == "geo_content.generate":
            from app.models import LLMProvider
            from app.models.cleanroom_v1 import GeoActionEvent, GeoContentBrief, GeoOptimizationAction, GeoWorkspace
            from app.v1.content_generation import generate_content_asset

            payload_json = dict(job.payload_json or {})
            workspace = db.get(GeoWorkspace, int(payload_json["workspace_id"]))
            brief = db.get(GeoContentBrief, int(payload_json["brief_id"]))
            provider = db.get(LLMProvider, int(payload_json["provider_id"]))
            if workspace is None or brief is None or provider is None:
                raise ValueError("Content generation workspace, brief or provider not found")
            asset = generate_content_asset(
                db,
                workspace,
                brief,
                provider,
                platform_key=str(payload_json.get("platform_key") or "official_site"),
            )
            action = db.get(GeoOptimizationAction, brief.action_id)
            if action is not None:
                previous_stage = action.stage
                action.stage = "draft_ready"
                action.status = "in_progress"
                action.blocked_reason = None
                db.add(
                    GeoActionEvent(
                        workspace_id=workspace.id,
                        action_id=action.id,
                        job_id=job.id,
                        event_type="content_generated",
                        from_stage=previous_stage,
                        to_stage="draft_ready",
                        actor_type="worker",
                        detail={"asset_id": asset.id, "provider_id": provider.id},
                    )
                )
            job.payload_json = {**payload_json, "stage": "complete", "asset_id": asset.id}
            job.status = "success"
            job.error_message = None
        else:
            raise ValueError(f"Unsupported job type: {job.job_type}")
    except Exception as exc:
        retryable = is_transient_job_error(exc) and job.attempts < job.max_attempts
        job.status = "pending" if retryable else "failed"
        detail = getattr(exc, "detail", None)
        job.error_message = str(detail or exc)
        if retryable:
            job.scheduled_at = datetime.now(UTC) + timedelta(
                seconds=retry_delay_seconds(job.attempts)
            )
    job.finished_at = datetime.now(UTC) if job.status in {"success", "failed"} else None
    db.add(job)
    sync_observation_task_from_job(db, job)
    db.commit()
    db.refresh(job)
    return job


def run_next_job(
    db: Session,
    now: datetime | None = None,
    project_id: int | None = None,
    project_ids: list[int] | None = None,
) -> QueueJob | None:
    job = claim_next_job(db, now=now, project_id=project_id, project_ids=project_ids)
    if job is None:
        return None
    return run_job(db, job)
