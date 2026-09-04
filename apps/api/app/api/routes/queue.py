from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import assert_company_access, get_project_or_404, require_roles
from app.db.session import get_db
from app.models import Project, QueueJob, User
from app.models.cleanroom_v1 import GeoWorkspace
from app.schemas.search import (
    QueueJobListResponse,
    QueueJobRead,
    QueueJobRunResult,
    QueueJobSummary,
    QueueReadyRunResult,
)
from app.services.audit import record_audit_log
from app.services.crawl_scheduler import run_due_crawl_schedules
from app.services.job_queue import apply_queue_tenant_filter, run_next_job

router = APIRouter(prefix="/queue", tags=["queue"])


def _exclude_non_dispatchable_history(stmt):
    """Keep legacy observations out of every executable queue surface."""

    return stmt.where(
        or_(
            QueueJob.job_type != "geo_observation.collect",
            QueueJob.status != "pending",
            QueueJob.payload_json["dispatch_enabled"].as_boolean().is_(True),
        )
    )


def _queue_summary(db: Session) -> QueueJobSummary:
    stmt = select(QueueJob.status, func.count()).group_by(QueueJob.status)
    rows = db.execute(_exclude_non_dispatchable_history(stmt)).all()
    counts = {status: count for status, count in rows}
    return QueueJobSummary(
        total=sum(counts.values()),
        pending=counts.get("pending", 0),
        running=counts.get("running", 0),
        success=counts.get("success", 0),
        failed=counts.get("failed", 0),
    )


def _queue_tenant_scope(db: Session, user: User) -> dict:
    if user.role == "super_admin":
        return {}
    if user.company_id is None:
        return {"company_id": -1, "project_ids": [], "workspace_ids": []}
    return {
        "company_id": user.company_id,
        "project_ids": list(
            db.scalars(select(Project.id).where(Project.company_id == user.company_id))
        ),
        "workspace_ids": list(
            db.scalars(select(GeoWorkspace.id).where(GeoWorkspace.company_id == user.company_id))
        ),
    }


def _queue_tenant_filter(stmt, scope: dict):
    if not scope:
        return stmt
    return apply_queue_tenant_filter(stmt, **scope)


def _queue_summary_for_user(db: Session, user: User) -> QueueJobSummary:
    scope = _queue_tenant_scope(db, user)
    stmt = select(QueueJob.status, func.count()).group_by(QueueJob.status)
    stmt = _queue_tenant_filter(stmt, scope)
    stmt = _exclude_non_dispatchable_history(stmt)
    rows = db.execute(stmt).all()
    counts = {status: count for status, count in rows}
    return QueueJobSummary(
        total=sum(counts.values()),
        pending=counts.get("pending", 0),
        running=counts.get("running", 0),
        success=counts.get("success", 0),
        failed=counts.get("failed", 0),
    )


@router.get("/jobs", response_model=QueueJobListResponse)
def list_queue_jobs(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin", "company_admin")),
) -> QueueJobListResponse:
    stmt = select(QueueJob).order_by(QueueJob.created_at.desc(), QueueJob.id.desc()).limit(limit)
    stmt = _queue_tenant_filter(stmt, _queue_tenant_scope(db, user))
    stmt = _exclude_non_dispatchable_history(stmt)
    if status:
        stmt = stmt.where(QueueJob.status == status)
    return QueueJobListResponse(summary=_queue_summary_for_user(db, user), jobs=list(db.scalars(stmt)))


@router.post("/jobs/run-next", response_model=QueueJobRunResult)
def run_next_queue_job(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin", "company_admin")),
) -> QueueJobRunResult:
    job = run_next_job(db, **_queue_tenant_scope(db, user))
    record_audit_log(
        db,
        user=user,
        action="queue.run_next",
        resource_type="queue_job",
        resource_id=job.id if job is not None else None,
        detail={"ran": job is not None, "status": job.status if job is not None else None},
    )
    db.commit()
    if job is None:
        return QueueJobRunResult(ran=False, job=None, message="当前没有可执行的队列任务。")
    db.refresh(job)
    return QueueJobRunResult(
        ran=True,
        job=QueueJobRead.model_validate(job),
        message=f"已执行队列任务 #{job.id}，状态 {job.status}。",
    )


@router.post("/jobs/run-ready", response_model=QueueReadyRunResult)
def run_ready_queue_jobs(
    max_jobs: int = Query(default=25, ge=1, le=100),
    project_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin", "company_admin")),
) -> QueueReadyRunResult:
    if project_id is not None:
        project = get_project_or_404(db, project_id)
        assert_company_access(user, project.company_id)
    scope = _queue_tenant_scope(db, user)
    project_ids = scope.get("project_ids")
    checked_at = datetime.now(UTC)
    _, tasks = run_due_crawl_schedules(db, project_id=project_id, project_ids=project_ids, now=checked_at)
    created_task_ids = [task.id for task in tasks]

    ran_jobs: list[QueueJob] = []
    for _ in range(max_jobs):
        if project_id is not None:
            job = run_next_job(db, project_id=project_id)
        else:
            job = run_next_job(db, **scope)
        if job is None:
            break
        ran_jobs.append(job)

    pending_checked_at = datetime.now(UTC)
    pending_stmt = (
        select(func.count())
        .select_from(QueueJob)
        .where(QueueJob.status == "pending")
        .where(QueueJob.scheduled_at <= pending_checked_at)
    )
    pending_stmt = _exclude_non_dispatchable_history(pending_stmt)
    if project_id is not None:
        pending_stmt = pending_stmt.where(
            QueueJob.payload_json["workspace_id"].as_integer().is_(None),
            QueueJob.payload_json["project_id"].as_integer() == project_id,
        )
    else:
        pending_stmt = _queue_tenant_filter(pending_stmt, scope)
    pending_job_count = db.scalar(pending_stmt) or 0
    success_job_count = sum(1 for job in ran_jobs if job.status == "success")
    failed_job_count = sum(1 for job in ran_jobs if job.status == "failed")
    message = (
        f"已创建 {len(created_task_ids)} 个到期采集任务，"
        f"执行 {len(ran_jobs)} 个队列任务，成功 {success_job_count} 个，失败 {failed_job_count} 个。"
    )
    if pending_job_count:
        message += f" 仍有 {pending_job_count} 个到期任务待执行。"

    record_audit_log(
        db,
        user=user,
        action="queue.run_ready",
        resource_type="queue_job",
        detail={
            "max_jobs": max_jobs,
            "project_id": project_id,
            "created_task_ids": created_task_ids,
            "ran_job_ids": [job.id for job in ran_jobs],
            "pending_job_count": pending_job_count,
        },
    )
    db.commit()
    return QueueReadyRunResult(
        checked_at=checked_at,
        created_task_ids=created_task_ids,
        ran_job_ids=[job.id for job in ran_jobs],
        ran_job_count=len(ran_jobs),
        success_job_count=success_job_count,
        failed_job_count=failed_job_count,
        pending_job_count=pending_job_count,
        message=message,
    )
