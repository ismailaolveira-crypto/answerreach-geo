from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, aliased

from app.models import (
    CrawlTask,
    CrawlTaskLog,
    GeoObservationBatch,
    GeoObservationTask,
    QueueJob,
    QueueWorkerHeartbeat,
)
from app.schemas.search import CrawlTaskCreate
from app.services.crawl_runner import run_crawl_task
from app.services.worker_heartbeat import (
    LEGACY_RUNNING_JOB_STALE_AFTER_SECONDS,
    WORKER_OFFLINE_AFTER_SECONDS,
    as_utc,
    worker_is_online,
)


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


def user_visible_job_error(job: QueueJob) -> str:
    error = str(job.error_message or "后台任务执行失败")
    if error.startswith("Unsupported job type:"):
        return "后台 Worker 版本过旧，请执行一键修复后重试"
    return error


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
        receipt = db.get(QueueJob, batch.queue_job_id) if batch.queue_job_id else None
        if completed + failed >= batch.total_tasks and batch.total_tasks > 0:
            batch.status = "completed" if failed == 0 else "partial"
            batch.completed_at = job.finished_at or datetime.now(UTC)
            if receipt is not None:
                receipt.status = (
                    "success" if failed == 0 else "failed" if completed == 0 else "partial"
                )
                receipt.finished_at = batch.completed_at
        elif running:
            batch.status = "running"
            batch.started_at = batch.started_at or job.started_at or datetime.now(UTC)
            batch.completed_at = None
            if receipt is not None:
                receipt.status = "running"
                receipt.started_at = receipt.started_at or batch.started_at
                receipt.finished_at = None
        else:
            batch.status = "pending"
            batch.completed_at = None
            if receipt is not None:
                receipt.status = "queued"
                receipt.finished_at = None
        if receipt is not None:
            db.add(receipt)
        db.add(batch)


def sync_agent_conversation_message_from_job(db: Session, job: QueueJob) -> None:
    """Keep the user-visible message aligned with the durable queue receipt."""

    if job.job_type != "geo_agent.conversation":
        return
    from app.models.cleanroom_v1 import GeoAgentConversationMessage

    message = db.scalar(
        select(GeoAgentConversationMessage).where(
            GeoAgentConversationMessage.job_id == job.id
        )
    )
    if message is None:
        return
    if job.status == "failed":
        message.status = "failed"
        message.error_message = user_visible_job_error(job)
    elif job.status == "pending" and message.status == "running":
        message.status = "queued"
        message.error_message = job.error_message
    db.add(message)


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


def recover_orphaned_jobs(
    db: Session,
    *,
    now: datetime | None = None,
    workspace_id: int | None = None,
) -> dict[str, int]:
    """Requeue only executable jobs whose owning Worker is no longer alive.

    Parent ``geo_observation.batch`` rows are orchestration receipts and remain
    derived from child task state; they are never executable or recovered here.
    """

    checked_at = now or datetime.now(UTC)
    stmt = select(QueueJob).where(
        QueueJob.status == "running",
        QueueJob.job_type != "geo_observation.batch",
    )
    if workspace_id is not None:
        stmt = stmt.where(
            QueueJob.payload_json["workspace_id"].as_integer() == workspace_id
        )
    workers = {
        worker.worker_id: worker
        for worker in db.scalars(select(QueueWorkerHeartbeat))
    }
    recovered = 0
    failed = 0
    for job in list(db.scalars(stmt.order_by(QueueJob.started_at.asc()))):
        started_at = as_utc(job.started_at)
        if started_at is None:
            continue
        payload = dict(job.payload_json or {})
        worker_id = str(payload.get("worker_id") or "").strip()
        worker = workers.get(worker_id)
        if worker_id:
            orphaned = not worker or not worker_is_online(worker, now=checked_at)
            stale_enough = started_at <= checked_at - timedelta(
                seconds=WORKER_OFFLINE_AFTER_SECONDS
            )
        else:
            orphaned = True
            stale_enough = started_at <= checked_at - timedelta(
                seconds=LEGACY_RUNNING_JOB_STALE_AFTER_SECONDS
            )
        if not orphaned or not stale_enough:
            continue
        claimed = db.execute(
            update(QueueJob)
            .where(QueueJob.id == job.id, QueueJob.status == "running")
            .values(status="recovering")
        )
        db.commit()
        if claimed.rowcount != 1:
            continue
        db.refresh(job)
        job.payload_json = {
            **payload,
            "worker_id": None,
            "recovery_count": int(payload.get("recovery_count") or 0) + 1,
        }
        if job.attempts < job.max_attempts:
            job.status = "pending"
            job.scheduled_at = checked_at
            job.started_at = None
            job.finished_at = None
            job.error_message = "上次 Worker 中断，任务已自动重新排队"
            recovered += 1
        else:
            job.status = "failed"
            job.finished_at = checked_at
            job.error_message = "Worker 中断且自动重试次数已用尽"
            failed += 1
        db.add(job)
        sync_observation_task_from_job(db, job)
        db.commit()
    return {"recovered": recovered, "failed": failed}


def claim_next_job(
    db: Session,
    now: datetime | None = None,
    project_id: int | None = None,
    project_ids: list[int] | None = None,
    workspace_id: int | None = None,
    observation_batch_id: int | None = None,
    worker_id: str | None = None,
) -> QueueJob | None:
    checked_at = now or datetime.now(UTC)
    stmt = (
        select(QueueJob)
        .where(QueueJob.status == "pending")
        .where(QueueJob.scheduled_at <= checked_at)
        .where(
            or_(
                QueueJob.job_type != "geo_observation.collect",
                QueueJob.payload_json["dispatch_enabled"].as_boolean().is_(True),
            )
        )
    )
    if workspace_id is not None:
        stmt = stmt.where(QueueJob.payload_json["workspace_id"].as_integer() == workspace_id)
    elif project_id is not None:
        stmt = stmt.where(QueueJob.payload_json["project_id"].as_integer() == project_id)
    elif project_ids is not None:
        if not project_ids:
            return None
        stmt = stmt.where(QueueJob.payload_json["project_id"].as_integer().in_(project_ids))
    if observation_batch_id is not None:
        stmt = stmt.where(
            QueueJob.payload_json["observation_ledger_batch_id"].as_integer()
            == observation_batch_id
        )
    # Prefer workspaces with fewer active jobs before job age. Without this
    # load-aware ordering, one older large workspace could occupy every slot in
    # personal mode and make another account look frozen even though the global
    # worker was healthy. Priority remains the first ordering key.
    running_job = aliased(QueueJob)
    candidate_workspace = QueueJob.payload_json["workspace_id"].as_integer()
    running_workspace = running_job.payload_json["workspace_id"].as_integer()
    active_workspace_jobs = (
        select(func.count(running_job.id))
        .where(
            running_job.status == "running",
            running_job.job_type != "geo_observation.batch",
            running_workspace == candidate_workspace,
        )
        .correlate(QueueJob)
        .scalar_subquery()
    )
    # Compare-and-swap prevents concurrent workers from claiming the same job.
    # This lets observation batches run with bounded concurrency without
    # duplicating paid model calls.
    for _ in range(5):
        job_id = db.scalar(
            stmt.with_only_columns(QueueJob.id)
            .order_by(
                QueueJob.priority.desc(),
                active_workspace_jobs.asc(),
                QueueJob.created_at.asc(),
            )
            .limit(1)
        )
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
                if worker_id:
                    job.payload_json = {
                        **dict(job.payload_json or {}),
                        "worker_id": worker_id,
                    }
                    db.add(job)
                sync_observation_task_from_job(db, job)
                db.commit()
                db.refresh(job)
            return job
    return None


def count_ready_jobs(
    db: Session,
    now: datetime | None = None,
    workspace_id: int | None = None,
    observation_batch_id: int | None = None,
) -> int:
    """Count jobs that the continuous Worker may claim right now.

    The Worker uses this lightweight coordinator query to grow its executor to
    actual demand.  In particular, an idle Worker must not start every allowed
    concurrency slot just to discover that the queue is empty; on SQLite that
    creates avoidable connection-pool pressure for normal API page reads.
    """

    checked_at = now or datetime.now(UTC)
    stmt = (
        select(func.count())
        .select_from(QueueJob)
        .where(QueueJob.status == "pending")
        .where(QueueJob.scheduled_at <= checked_at)
        .where(
            or_(
                QueueJob.job_type != "geo_observation.collect",
                QueueJob.payload_json["dispatch_enabled"].as_boolean().is_(True),
            )
        )
    )
    if workspace_id is not None:
        stmt = stmt.where(
            QueueJob.payload_json["workspace_id"].as_integer() == workspace_id
        )
    if observation_batch_id is not None:
        stmt = stmt.where(
            QueueJob.payload_json["observation_ledger_batch_id"].as_integer()
            == observation_batch_id
        )
    return int(db.scalar(stmt) or 0)


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
            from app.models import User
            from app.v1.observation_service import collect_provider_web_search
            from app.v1.schemas import OfficialApiObservationRequest

            payload_json = dict(job.payload_json or {})
            user = db.get(User, int(payload_json["actor_user_id"]))
            if user is None:
                raise ValueError("Observation job actor no longer exists")
            result = collect_provider_web_search(
                db,
                workspace_id=int(payload_json["workspace_id"]),
                payload=OfficialApiObservationRequest(
                    question_plan_id=int(payload_json["question_plan_id"]),
                    provider_id=int(payload_json["provider_id"]),
                    repeat_index=int(payload_json.get("repeat_index") or 1),
                    repeat_count=int(payload_json.get("repeat_count") or 1),
                    observation_group_id=payload_json.get("observation_group_id"),
                ),
                user=user,
                observation_task_id=int(payload_json.get("observation_task_id") or 0),
            )
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
            from app.models import LLMProvider, User
            from app.schemas.search import LLMProviderTestRequest
            from app.services.provider_testing import run_provider_test

            payload_json = dict(job.payload_json or {})
            user = db.get(User, int(payload_json["actor_user_id"]))
            if user is None:
                raise ValueError("Provider test job actor no longer exists")
            provider = db.get(LLMProvider, int(payload_json["provider_id"]))
            if provider is None:
                raise ValueError("Provider test job channel no longer exists")
            job.payload_json = {**payload_json, "stage": "testing"}
            db.add(job)
            db.commit()
            db.refresh(job)
            result = run_provider_test(
                db,
                provider=provider,
                payload=LLMProviderTestRequest(
                    prompt_text=str(payload_json.get("prompt_text") or "企业级大模型治理平台怎么选？"),
                    company_name=str(payload_json.get("company_name") or "示例企业"),
                    industry=str(payload_json.get("industry") or "网络安全"),
                ),
                user=user,
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
        elif job.job_type == "geo_agent.run":
            from app.models.cleanroom_v1 import GeoAgentRun
            from app.v1.agent_orchestration import execute_agent_run

            payload_json = dict(job.payload_json or {})
            run = db.get(GeoAgentRun, int(payload_json["agent_run_id"]))
            if run is None:
                raise ValueError("Agent run not found")
            result = execute_agent_run(db, run)
            job.payload_json = {
                **payload_json,
                "stage": result.stage,
                "agent_status": result.status,
                "asset_id": (result.result_snapshot or {}).get("asset_id"),
            }
            job.status = "success" if result.status in {"awaiting_review", "cancelled"} else "failed"
            job.error_message = result.error_message
        elif job.job_type == "geo_agent.conversation":
            from app.models.cleanroom_v1 import GeoAgentConversationMessage
            from app.v1.agent_workspace import execute_agent_workspace_message

            payload_json = dict(job.payload_json or {})
            message = db.get(
                GeoAgentConversationMessage, int(payload_json["message_id"])
            )
            if message is None:
                raise ValueError("Agent conversation message not found")
            result = execute_agent_workspace_message(db, message)
            job.payload_json = {
                **payload_json,
                "stage": "complete",
                "message_status": result.status,
            }
            job.status = "success"
            job.error_message = None
        elif job.job_type == "geo_opportunity.discover":
            from app.v1.opportunity_agent import execute_opportunity_analysis

            payload_json = dict(job.payload_json or {})
            result = execute_opportunity_analysis(db, job)
            job.payload_json = {
                **dict(job.payload_json or payload_json),
                **result,
            }
            job.status = "success"
            job.error_message = None
        elif job.job_type == "geo_website_gap.analyze":
            from app.v1.website_gap_agent import execute_website_gap_analysis

            payload_json = dict(job.payload_json or {})
            result = execute_website_gap_analysis(db, job)
            job.payload_json = {
                **dict(job.payload_json or payload_json),
                **result,
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
    sync_agent_conversation_message_from_job(db, job)
    db.commit()
    db.refresh(job)
    return job


def run_next_job(
    db: Session,
    now: datetime | None = None,
    project_id: int | None = None,
    project_ids: list[int] | None = None,
    workspace_id: int | None = None,
    observation_batch_id: int | None = None,
    worker_id: str | None = None,
) -> QueueJob | None:
    job = claim_next_job(
        db,
        now=now,
        project_id=project_id,
        project_ids=project_ids,
        workspace_id=workspace_id,
        observation_batch_id=observation_batch_id,
        worker_id=worker_id,
    )
    if job is None:
        return None
    return run_job(db, job)
