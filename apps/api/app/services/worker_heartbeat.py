"""Queue worker liveness and workspace-facing status summaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import QueueJob, QueueWorkerHeartbeat


WORKER_HEARTBEAT_INTERVAL_SECONDS = 15
WORKER_OFFLINE_AFTER_SECONDS = 120
WORKER_HEARTBEAT_FAILURE_LIMIT = 4
LEGACY_RUNNING_JOB_STALE_AFTER_SECONDS = 15 * 60


@dataclass(frozen=True)
class WorkerRegistration:
    worker_id: str
    mode: str
    hostname: str
    process_id: int
    concurrency: int
    workspace_id: int | None
    observation_batch_id: int | None


@dataclass
class HeartbeatFailureBudget:
    """Escalate sustained monitoring failure without reacting to one hiccup."""

    limit: int = WORKER_HEARTBEAT_FAILURE_LIMIT
    consecutive_failures: int = 0

    def record_success(self) -> None:
        self.consecutive_failures = 0

    def record_failure(self) -> bool:
        self.consecutive_failures += 1
        return self.consecutive_failures >= self.limit


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def worker_is_online(
    worker: QueueWorkerHeartbeat,
    *,
    now: datetime | None = None,
) -> bool:
    checked_at = now or datetime.now(UTC)
    last_seen_at = as_utc(worker.last_seen_at)
    return bool(
        worker.status == "active"
        and last_seen_at is not None
        and last_seen_at >= checked_at - timedelta(seconds=WORKER_OFFLINE_AFTER_SECONDS)
    )


def register_worker(
    db: Session,
    *,
    worker_id: str,
    mode: str,
    hostname: str,
    process_id: int,
    concurrency: int,
    workspace_id: int | None,
    observation_batch_id: int | None,
    now: datetime | None = None,
) -> QueueWorkerHeartbeat:
    checked_at = now or datetime.now(UTC)
    worker = db.scalar(
        select(QueueWorkerHeartbeat).where(QueueWorkerHeartbeat.worker_id == worker_id)
    )
    if worker is None:
        worker = QueueWorkerHeartbeat(worker_id=worker_id)
    worker.status = "active"
    worker.mode = mode
    worker.hostname = hostname
    worker.process_id = process_id
    worker.concurrency = concurrency
    worker.workspace_id = workspace_id
    worker.observation_batch_id = observation_batch_id
    worker.started_at = checked_at
    worker.last_seen_at = checked_at
    worker.stopped_at = None
    db.add(worker)
    db.commit()
    db.refresh(worker)
    return worker


def touch_or_register_worker(
    db: Session,
    registration: WorkerRegistration,
    *,
    now: datetime | None = None,
) -> str:
    """Refresh liveness, recreating a missing row instead of staying invisible."""

    if touch_worker(db, registration.worker_id, now=now):
        return "touched"
    register_worker(
        db,
        worker_id=registration.worker_id,
        mode=registration.mode,
        hostname=registration.hostname,
        process_id=registration.process_id,
        concurrency=registration.concurrency,
        workspace_id=registration.workspace_id,
        observation_batch_id=registration.observation_batch_id,
        now=now,
    )
    return "registered"


def touch_worker(
    db: Session,
    worker_id: str,
    *,
    now: datetime | None = None,
) -> bool:
    worker = db.scalar(
        select(QueueWorkerHeartbeat).where(QueueWorkerHeartbeat.worker_id == worker_id)
    )
    if worker is None:
        return False
    worker.status = "active"
    worker.last_seen_at = now or datetime.now(UTC)
    worker.stopped_at = None
    db.add(worker)
    db.commit()
    return True


def stop_worker(
    db: Session,
    worker_id: str,
    *,
    now: datetime | None = None,
) -> bool:
    worker = db.scalar(
        select(QueueWorkerHeartbeat).where(QueueWorkerHeartbeat.worker_id == worker_id)
    )
    if worker is None:
        return False
    checked_at = now or datetime.now(UTC)
    worker.status = "stopped"
    worker.last_seen_at = checked_at
    worker.stopped_at = checked_at
    db.add(worker)
    db.commit()
    return True


def _workspace_jobs(db: Session, workspace_id: int, status: str) -> list[QueueJob]:
    return list(
        db.scalars(
            select(QueueJob).where(
                QueueJob.job_type != "geo_observation.batch",
                QueueJob.status == status,
                QueueJob.payload_json["workspace_id"].as_integer() == workspace_id,
            )
        )
    )


def _is_dispatchable(job: QueueJob) -> bool:
    """Only a fresh, explicit page submission can dispatch an observation.

    Legacy observation rows intentionally have no marker. They remain readable
    history but are never counted as executable work and can never be claimed
    merely because a Worker starts.
    """

    return job.job_type != "geo_observation.collect" or bool(
        dict(job.payload_json or {}).get("dispatch_enabled") is True
    )


def online_workers_for_workspace(
    db: Session,
    workspace_id: int,
    *,
    now: datetime | None = None,
) -> list[QueueWorkerHeartbeat]:
    """Return live continuous workers that are allowed to serve a workspace.

    A global worker has no workspace scope and serves every account/workspace.
    Batch-scoped workers are recovery/diagnostic processes, so they must not make
    the regular observation composer appear generally available.
    """

    checked_at = now or datetime.now(UTC)
    workers = list(
        db.scalars(
            select(QueueWorkerHeartbeat)
            .where(
                QueueWorkerHeartbeat.mode == "continuous",
                QueueWorkerHeartbeat.observation_batch_id.is_(None),
                or_(
                    QueueWorkerHeartbeat.workspace_id.is_(None),
                    QueueWorkerHeartbeat.workspace_id == workspace_id,
                ),
            )
            .order_by(QueueWorkerHeartbeat.last_seen_at.desc())
        )
    )
    return [worker for worker in workers if worker_is_online(worker, now=checked_at)]


def online_global_workers(
    db: Session,
    *,
    process_id: int | None = None,
    now: datetime | None = None,
) -> list[QueueWorkerHeartbeat]:
    """Return live unscoped continuous workers, optionally for one exact PID."""

    checked_at = now or datetime.now(UTC)
    stmt = select(QueueWorkerHeartbeat).where(
        QueueWorkerHeartbeat.mode == "continuous",
        QueueWorkerHeartbeat.workspace_id.is_(None),
        QueueWorkerHeartbeat.observation_batch_id.is_(None),
    )
    if process_id is not None:
        stmt = stmt.where(QueueWorkerHeartbeat.process_id == process_id)
    workers = list(db.scalars(stmt.order_by(QueueWorkerHeartbeat.last_seen_at.desc())))
    return [worker for worker in workers if worker_is_online(worker, now=checked_at)]


def workspace_worker_is_online(
    db: Session,
    workspace_id: int,
    *,
    now: datetime | None = None,
) -> bool:
    return bool(online_workers_for_workspace(db, workspace_id, now=now))


def get_workspace_worker_status(
    db: Session,
    workspace_id: int,
    *,
    now: datetime | None = None,
) -> dict:
    checked_at = now or datetime.now(UTC)
    all_scoped_workers = list(
        db.scalars(
            select(QueueWorkerHeartbeat)
            .where(
                QueueWorkerHeartbeat.mode == "continuous",
                QueueWorkerHeartbeat.observation_batch_id.is_(None),
                or_(
                    QueueWorkerHeartbeat.workspace_id.is_(None),
                    QueueWorkerHeartbeat.workspace_id == workspace_id,
                )
            )
            .order_by(QueueWorkerHeartbeat.last_seen_at.desc())
        )
    )
    online_workers = online_workers_for_workspace(db, workspace_id, now=checked_at)
    all_pending_jobs = _workspace_jobs(db, workspace_id, "pending")
    pending_jobs = [job for job in all_pending_jobs if _is_dispatchable(job)]
    historical_jobs = [job for job in all_pending_jobs if not _is_dispatchable(job)]
    running_jobs = _workspace_jobs(db, workspace_id, "running")
    stale_cutoff = checked_at - timedelta(seconds=LEGACY_RUNNING_JOB_STALE_AFTER_SECONDS)
    stale_running_jobs = [
        job
        for job in running_jobs
        if as_utc(job.started_at) is not None and as_utc(job.started_at) < stale_cutoff
    ]
    online = bool(online_workers)
    last_seen_source = online_workers[0] if online_workers else (
        all_scoped_workers[0] if all_scoped_workers else None
    )
    last_seen_at = as_utc(last_seen_source.last_seen_at) if last_seen_source else None
    capacity = sum(worker.concurrency for worker in online_workers)
    if online:
        message = (
            f"采集服务在线，只处理当前页面新提交的 {len(pending_jobs)} 条任务。"
            if pending_jobs
            else "采集服务在线，当前没有新提交的可执行任务。"
        )
    elif pending_jobs:
        message = f"采集服务离线，{len(pending_jobs)} 条新提交任务将保留在队列中。"
    else:
        message = "采集服务离线，当前没有新提交的可执行任务。"
    if historical_jobs:
        message += f" {len(historical_jobs)} 条历史任务仅保留记录，不会执行。"
    return {
        "workspace_id": workspace_id,
        "online": online,
        "status": "online" if online else "offline",
        "worker_count": len(online_workers),
        "concurrency": capacity,
        "pending_jobs": len(pending_jobs),
        "historical_jobs": len(historical_jobs),
        "running_jobs": len(running_jobs),
        "stale_running_jobs": len(stale_running_jobs),
        "last_seen_at": last_seen_at,
        "heartbeat_interval_seconds": WORKER_HEARTBEAT_INTERVAL_SECONDS,
        "offline_after_seconds": WORKER_OFFLINE_AFTER_SECONDS,
        "message": message,
    }
