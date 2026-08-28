from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import WRITE_ROLES, get_current_user, require_roles
from app.db.session import get_db
from app.models import LLMProvider
from app.models.cleanroom_v1 import (
    GeoActionEvent,
    GeoActionTarget,
    GeoChangeAlert,
    GeoObservationBatch,
    GeoObservationSchedule,
    GeoObservationScheduleRun,
    GeoOptimizationAction,
    GeoQuestionPlan,
)
from app.models.user import User
from app.services.workspace_access import require_workspace_access
from app.v1.observation_alerts import (
    canonical_fingerprint,
    evaluate_change_alerts,
    latest_comparable_batch,
    next_schedule_time,
    schedule_scope,
    schedule_window_key,
)


router = APIRouter(prefix="/v1", tags=["geo-observation-alerts-v1"])


class ScheduleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    cadence: Literal["daily", "weekly", "custom"] = "daily"
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    local_time: str = "09:00"
    timezone_name: str = "Asia/Shanghai"
    provider_ids: list[int] = Field(min_length=1, max_length=5)
    question_plan_ids: list[int] = Field(min_length=1, max_length=100)
    repeat_count: int = Field(default=2, ge=1, le=5)

    @field_validator("weekdays")
    @classmethod
    def validate_weekdays(cls, value: list[int]) -> list[int]:
        if any(day < 0 or day > 6 for day in value):
            raise ValueError("weekdays must use 0-6")
        return sorted(set(value))

    @field_validator("local_time")
    @classmethod
    def validate_local_time(cls, value: str) -> str:
        try:
            hour, minute = (int(item) for item in value.split(":"))
            if hour not in range(24) or minute not in range(60):
                raise ValueError
        except (ValueError, TypeError) as exc:
            raise ValueError("local_time must be HH:MM") from exc
        return f"{hour:02d}:{minute:02d}"


class ScheduleStatusUpdate(BaseModel):
    status: Literal["active", "paused"]


class AlertStatusUpdate(BaseModel):
    status: Literal["confirmed", "ignored"]


def _iso(value: datetime | None) -> datetime | None:
    return value


def _schedule_read(row: GeoObservationSchedule) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "status": row.status,
        "cadence": row.cadence,
        "weekdays": row.weekdays,
        "local_time": row.local_time,
        "timezone_name": row.timezone_name,
        "provider_ids": row.provider_ids,
        "question_plan_ids": row.question_plan_ids,
        "repeat_count": row.repeat_count,
        "scope_snapshot": row.scope_snapshot,
        "scope_fingerprint": row.scope_fingerprint,
        "scope_version": row.scope_version,
        "next_run_at": _iso(row.next_run_at),
        "last_run_at": _iso(row.last_run_at),
    }


def _run_read(row: GeoObservationScheduleRun) -> dict:
    return {
        "id": row.id,
        "schedule_id": row.schedule_id,
        "window_key": row.window_key,
        "status": row.status,
        "batch_id": row.batch_id,
        "baseline_batch_id": row.baseline_batch_id,
        "scope_snapshot": row.scope_snapshot,
        "scope_fingerprint": row.scope_fingerprint,
        "scheduled_for": row.scheduled_for,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
        "failure_reason": row.failure_reason,
    }


def _alert_read(row: GeoChangeAlert) -> dict:
    return {
        "id": row.id,
        "alert_type": row.alert_type,
        "severity": row.severity,
        "status": row.status,
        "title": row.title,
        "summary": row.summary,
        "baseline_batch_id": row.baseline_batch_id,
        "current_batch_id": row.current_batch_id,
        "scope_snapshot": row.scope_snapshot,
        "completeness": row.completeness,
        "metric_snapshot": row.metric_snapshot,
        "evidence_ids": row.evidence_ids,
        "suggested_action": row.suggested_action,
        "converted_action_id": row.converted_action_id,
        "created_at": row.created_at,
        "resolved_at": row.resolved_at,
    }


def _validate_scope(db: Session, workspace_id: int, payload: ScheduleCreate) -> None:
    providers = list(db.scalars(select(LLMProvider).where(LLMProvider.id.in_(payload.provider_ids))))
    if len({row.id for row in providers}) != len(set(payload.provider_ids)):
        raise HTTPException(status_code=422, detail="部分模型不存在")
    questions = list(
        db.scalars(
            select(GeoQuestionPlan).where(
                GeoQuestionPlan.workspace_id == workspace_id,
                GeoQuestionPlan.id.in_(payload.question_plan_ids),
                GeoQuestionPlan.active.is_(True),
            )
        )
    )
    if len({row.id for row in questions}) != len(set(payload.question_plan_ids)):
        raise HTTPException(status_code=422, detail="部分问题已停用或不属于当前工作区")


@router.post("/workspaces/{workspace_id}/observation-schedules", status_code=201)
def create_observation_schedule(
    workspace_id: int,
    payload: ScheduleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    require_workspace_access(db, user, workspace_id)
    _validate_scope(db, workspace_id, payload)
    scope = schedule_scope(payload.provider_ids, payload.question_plan_ids, payload.repeat_count)
    try:
        next_run_at = next_schedule_time(
            cadence=payload.cadence,
            weekdays=payload.weekdays,
            local_time=payload.local_time,
            timezone_name=payload.timezone_name,
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail="时区或运行时间无效") from exc
    row = GeoObservationSchedule(
        workspace_id=workspace_id,
        name=payload.name.strip(),
        status="active",
        cadence=payload.cadence,
        weekdays=payload.weekdays,
        local_time=payload.local_time,
        timezone_name=payload.timezone_name,
        provider_ids=scope["provider_ids"],
        question_plan_ids=scope["question_plan_ids"],
        repeat_count=payload.repeat_count,
        scope_snapshot=scope,
        scope_fingerprint=canonical_fingerprint(scope),
        scope_version=1,
        next_run_at=next_run_at,
        created_by_user_id=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _schedule_read(row)


@router.patch("/workspaces/{workspace_id}/observation-schedules/{schedule_id}")
def update_observation_schedule_status(
    workspace_id: int,
    schedule_id: int,
    payload: ScheduleStatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    require_workspace_access(db, user, workspace_id)
    row = db.get(GeoObservationSchedule, schedule_id)
    if row is None or row.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="观测计划不存在")
    row.status = payload.status
    if payload.status == "active":
        row.next_run_at = next_schedule_time(
            cadence=row.cadence, weekdays=row.weekdays, local_time=row.local_time,
            timezone_name=row.timezone_name,
        )
    db.commit()
    db.refresh(row)
    return _schedule_read(row)


def _create_run_receipt(
    db: Session, schedule: GeoObservationSchedule, scheduled_for: datetime, *, manual: bool,
) -> GeoObservationScheduleRun:
    window_key = (
        f"manual:{scheduled_for.strftime('%Y%m%dT%H%M%S%f')}"
        if manual else schedule_window_key(schedule, scheduled_for)
    )
    existing = db.scalar(
        select(GeoObservationScheduleRun).where(
            GeoObservationScheduleRun.schedule_id == schedule.id,
            GeoObservationScheduleRun.window_key == window_key,
        )
    )
    if existing:
        return existing
    baseline = latest_comparable_batch(
        db, workspace_id=schedule.workspace_id, scope=schedule.scope_snapshot
    )
    row = GeoObservationScheduleRun(
        workspace_id=schedule.workspace_id,
        schedule_id=schedule.id,
        window_key=window_key,
        status="queued",
        baseline_batch_id=baseline.id if baseline else None,
        scope_snapshot=schedule.scope_snapshot,
        scope_fingerprint=schedule.scope_fingerprint,
        scheduled_for=scheduled_for,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return db.scalar(
            select(GeoObservationScheduleRun).where(
                GeoObservationScheduleRun.schedule_id == schedule.id,
                GeoObservationScheduleRun.window_key == window_key,
            )
        )
    return row


def _dispatch_run(db: Session, run: GeoObservationScheduleRun, schedule: GeoObservationSchedule, user: User) -> None:
    from app.v1.routes import OfficialApiObservationBatchCreate, create_provider_web_search_batch

    run.started_at = datetime.now(UTC)
    run.status = "dispatching"
    db.commit()
    try:
        batch = create_provider_web_search_batch(
            schedule.workspace_id,
            OfficialApiObservationBatchCreate(
                provider_ids=schedule.provider_ids,
                question_plan_ids=schedule.question_plan_ids,
                repeat_count=schedule.repeat_count,
            ),
            db,
            user,
        )
        batch_id = int(batch["batch_id"] if isinstance(batch, dict) else batch.batch_id)
        run = db.get(GeoObservationScheduleRun, run.id)
        assert run is not None
        run.batch_id = batch_id
        run.status = "running"
        schedule.last_run_at = run.started_at
        schedule.next_run_at = next_schedule_time(
            cadence=schedule.cadence, weekdays=schedule.weekdays,
            local_time=schedule.local_time, timezone_name=schedule.timezone_name,
            after=run.started_at,
        )
        db.commit()
    except Exception as exc:
        run = db.get(GeoObservationScheduleRun, run.id)
        assert run is not None
        run.status = "failed"
        detail = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
        run.failure_reason = detail[:500] or "观测计划分发失败"
        run.completed_at = datetime.now(UTC)
        db.commit()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=f"观测计划分发失败：{detail}") from exc


@router.post("/workspaces/{workspace_id}/observation-schedules/{schedule_id}/run", status_code=202)
def run_observation_schedule_now(
    workspace_id: int,
    schedule_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    require_workspace_access(db, user, workspace_id)
    schedule = db.get(GeoObservationSchedule, schedule_id)
    if schedule is None or schedule.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="观测计划不存在")
    now = datetime.now(UTC)
    run = _create_run_receipt(db, schedule, now, manual=True)
    db.commit()
    _dispatch_run(db, run, schedule, user)
    db.refresh(run)
    return _run_read(run)


@router.post("/workspaces/{workspace_id}/observation-schedules/run-due")
def run_due_observation_schedules(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    require_workspace_access(db, user, workspace_id)
    now = datetime.now(UTC)
    schedules = list(
        db.scalars(
            select(GeoObservationSchedule).where(
                GeoObservationSchedule.workspace_id == workspace_id,
                GeoObservationSchedule.status == "active",
                GeoObservationSchedule.next_run_at <= now,
            )
        )
    )
    results = []
    for schedule in schedules:
        run = _create_run_receipt(db, schedule, schedule.next_run_at, manual=False)
        db.commit()
        if run.status == "queued":
            try:
                _dispatch_run(db, run, schedule, user)
            except HTTPException:
                pass
        results.append(_run_read(db.get(GeoObservationScheduleRun, run.id)))
    return {"runs": results}


def _synchronize_completed_runs(db: Session, workspace_id: int) -> None:
    runs = list(
        db.scalars(
            select(GeoObservationScheduleRun).where(
                GeoObservationScheduleRun.workspace_id == workspace_id,
                GeoObservationScheduleRun.status == "running",
            )
        )
    )
    for run in runs:
        batch = db.get(GeoObservationBatch, run.batch_id) if run.batch_id else None
        if batch is None or batch.status not in {"completed", "success", "partial", "failed"}:
            continue
        baseline = db.get(GeoObservationBatch, run.baseline_batch_id) if run.baseline_batch_id else None
        evaluate_change_alerts(db, run=run, current=batch, baseline=baseline)
    db.commit()


def process_observation_schedules(
    db: Session, *, workspace_id: int | None = None, now: datetime | None = None
) -> dict:
    """Worker entrypoint: evaluate completed runs, then dispatch each due window once."""

    checked_at = now or datetime.now(UTC)
    workspace_ids = set(
        db.scalars(
            select(GeoObservationSchedule.workspace_id).where(
                GeoObservationSchedule.status == "active",
                *(
                    (GeoObservationSchedule.workspace_id == workspace_id,)
                    if workspace_id is not None
                    else ()
                ),
            )
        )
    )
    for scoped_workspace_id in workspace_ids:
        _synchronize_completed_runs(db, scoped_workspace_id)
    due_query = select(GeoObservationSchedule).where(
        GeoObservationSchedule.status == "active",
        GeoObservationSchedule.next_run_at <= checked_at,
    )
    if workspace_id is not None:
        due_query = due_query.where(GeoObservationSchedule.workspace_id == workspace_id)
    schedules = list(db.scalars(due_query.order_by(GeoObservationSchedule.next_run_at)))
    dispatched = failed = deduplicated = 0
    for schedule in schedules:
        scheduled_for = schedule.next_run_at
        run = _create_run_receipt(db, schedule, scheduled_for, manual=False)
        db.commit()
        if run.status != "queued":
            deduplicated += 1
            schedule.next_run_at = next_schedule_time(
                cadence=schedule.cadence,
                weekdays=schedule.weekdays,
                local_time=schedule.local_time,
                timezone_name=schedule.timezone_name,
                after=scheduled_for,
            )
            db.commit()
            continue
        actor = db.get(User, schedule.created_by_user_id) if schedule.created_by_user_id else None
        if actor is None:
            run.status = "failed"
            run.failure_reason = "观测计划的创建人已不存在，请重新创建计划"
            run.completed_at = checked_at
            schedule.next_run_at = next_schedule_time(
                cadence=schedule.cadence,
                weekdays=schedule.weekdays,
                local_time=schedule.local_time,
                timezone_name=schedule.timezone_name,
                after=scheduled_for,
            )
            db.commit()
            failed += 1
            continue
        try:
            _dispatch_run(db, run, schedule, actor)
            dispatched += 1
        except HTTPException:
            schedule.next_run_at = next_schedule_time(
                cadence=schedule.cadence,
                weekdays=schedule.weekdays,
                local_time=schedule.local_time,
                timezone_name=schedule.timezone_name,
                after=scheduled_for,
            )
            db.commit()
            failed += 1
    return {
        "checked_at": checked_at.isoformat(),
        "dispatched": dispatched,
        "failed": failed,
        "deduplicated": deduplicated,
    }


_WORKER_INTERRUPTION_MARKERS = (
    "采集服务当前离线",
    "queue worker",
    "worker offline",
)


def retry_worker_interrupted_schedule_runs(
    db: Session,
    *,
    workspace_id: int,
    actor: User,
    now: datetime | None = None,
    limit: int = 3,
) -> dict:
    """Retry only the latest schedule failure caused by an offline Worker.

    A repair must not replay arbitrary business failures or an obsolete scope.
    For each active schedule we therefore inspect only its latest receipt, require
    an explicit Worker-interruption marker, and require the stored scope to still
    match the schedule. A manual receipt makes the retry independently auditable.
    """

    checked_at = now or datetime.now(UTC)
    schedules = list(
        db.scalars(
            select(GeoObservationSchedule)
            .where(
                GeoObservationSchedule.workspace_id == workspace_id,
                GeoObservationSchedule.status == "active",
            )
            .order_by(GeoObservationSchedule.id)
        )
    )
    retried = failed = skipped_scope_changed = 0
    for schedule in schedules:
        if retried + failed >= limit:
            break
        latest = db.scalar(
            select(GeoObservationScheduleRun)
            .where(GeoObservationScheduleRun.schedule_id == schedule.id)
            .order_by(
                GeoObservationScheduleRun.created_at.desc(),
                GeoObservationScheduleRun.id.desc(),
            )
            .limit(1)
        )
        if latest is None or latest.status != "failed":
            continue
        reason = (latest.failure_reason or "").casefold()
        if not any(marker in reason for marker in _WORKER_INTERRUPTION_MARKERS):
            continue
        if latest.scope_fingerprint != schedule.scope_fingerprint:
            skipped_scope_changed += 1
            continue

        retry = _create_run_receipt(db, schedule, checked_at, manual=True)
        db.commit()
        try:
            _dispatch_run(db, retry, schedule, actor)
            retried += 1
        except HTTPException:
            failed += 1

    return {
        "checked_at": checked_at.isoformat(),
        "retried": retried,
        "failed": failed,
        "skipped_scope_changed": skipped_scope_changed,
    }


@router.get("/workspaces/{workspace_id}/observation-alert-center")
def get_observation_alert_center(
    workspace_id: int,
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_workspace_access(db, user, workspace_id)
    _synchronize_completed_runs(db, workspace_id)
    schedules = list(
        db.scalars(
            select(GeoObservationSchedule)
            .where(GeoObservationSchedule.workspace_id == workspace_id)
            .order_by(GeoObservationSchedule.status, GeoObservationSchedule.next_run_at)
        )
    )
    alert_query = select(GeoChangeAlert).where(GeoChangeAlert.workspace_id == workspace_id)
    if status:
        alert_query = alert_query.where(GeoChangeAlert.status == status)
    alerts = list(db.scalars(alert_query.order_by(GeoChangeAlert.created_at.desc(), GeoChangeAlert.id.desc()).limit(100)))
    runs = list(
        db.scalars(
            select(GeoObservationScheduleRun)
            .where(GeoObservationScheduleRun.workspace_id == workspace_id)
            .order_by(GeoObservationScheduleRun.created_at.desc(), GeoObservationScheduleRun.id.desc())
            .limit(50)
        )
    )
    completed = [row for row in runs if row.status == "evaluated"]
    complete_runs = sum(
        bool((alert.completeness or {}).get("current_complete"))
        for alert in alerts
        if alert.schedule_run_id in {row.id for row in completed}
    )
    return {
        "summary": {
            "active_schedules": sum(row.status == "active" for row in schedules),
            "today_runs": sum(
                row.created_at.date() == datetime.now(UTC).date() for row in runs
            ),
            "open_alerts": sum(row.status == "open" for row in alerts),
            "data_completeness": round(complete_runs / len(completed), 4) if completed else None,
        },
        "schedules": [_schedule_read(row) for row in schedules],
        "alerts": [_alert_read(row) for row in alerts],
        "runs": [_run_read(row) for row in runs],
    }


@router.patch("/workspaces/{workspace_id}/change-alerts/{alert_id}")
def update_change_alert(
    workspace_id: int,
    alert_id: int,
    payload: AlertStatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    require_workspace_access(db, user, workspace_id)
    row = db.get(GeoChangeAlert, alert_id)
    if row is None or row.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="告警不存在")
    row.status = payload.status
    row.resolved_by_user_id = user.id
    row.resolved_at = datetime.now(UTC)
    db.commit()
    db.refresh(row)
    return _alert_read(row)


@router.post("/workspaces/{workspace_id}/change-alerts/{alert_id}/convert-to-action", status_code=201)
def convert_change_alert_to_action(
    workspace_id: int,
    alert_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    require_workspace_access(db, user, workspace_id)
    alert = db.get(GeoChangeAlert, alert_id)
    if alert is None or alert.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="告警不存在")
    if alert.converted_action_id:
        action = db.get(GeoOptimizationAction, alert.converted_action_id)
        return {"action_id": action.id, "created": False}
    action_type = str((alert.suggested_action or {}).get("action_type") or "article")
    if action_type == "observation_recovery":
        action_type = "official_site"
    questions = sorted(set(int(value) for value in (alert.scope_snapshot or {}).get("question_plan_ids") or []))
    action = GeoOptimizationAction(
        workspace_id=workspace_id,
        question_plan_id=questions[0] if questions else None,
        title=alert.title,
        rationale=f"由变化告警 #{alert.id} 转入：{alert.summary}",
        hypothesis="处理该变化信号后，以相同范围复测验证是否恢复。",
        priority="high" if alert.severity == "critical" else "medium",
        status="proposed",
        stage="selected",
        baseline_snapshot={"batch_id": alert.current_batch_id, "alert_id": alert.id},
        selected_scope=alert.scope_snapshot,
        measurement_plan={"schema": "alert-followup/v1", "baseline_batch_id": alert.current_batch_id},
        action_type=action_type,
        deliverable_type={
            "article": "article_draft",
            "official_site": "official_site_change",
            "structured_data": "structured_data_patch",
            "third_party_source": "source_placement",
        }.get(action_type, "article_draft"),
        workflow_version="action-flow.v2",
        affected_question_ids=questions,
        affected_model_keys=[],
        scope_fingerprint=canonical_fingerprint(alert.scope_snapshot or {}),
        measurement_status="not_eligible",
    )
    db.add(action)
    db.flush()
    target = GeoActionTarget(
        workspace_id=workspace_id,
        action_id=action.id,
        target_key=f"alert:{alert.id}:primary",
        target_type="platform" if action_type == "article" else "official_page",
        display_name="待选择执行目标",
        target_ref=f"change-alert:{alert.id}",
        delivery_status="target_selected" if action_type == "article" else "gap_confirmed",
        ordinal=0,
        metadata_json={"source_alert_id": alert.id},
    )
    db.add(target)
    db.add(GeoActionEvent(
        workspace_id=workspace_id,
        action_id=action.id,
        event_type="created_from_change_alert",
        to_stage="selected",
        actor_type="user",
        actor_user_id=user.id,
        detail={"alert_id": alert.id, "current_batch_id": alert.current_batch_id},
    ))
    alert.converted_action_id = action.id
    alert.status = "confirmed"
    alert.resolved_by_user_id = user.id
    alert.resolved_at = datetime.now(UTC)
    db.commit()
    return {"action_id": action.id, "created": True}
