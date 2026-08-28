from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import WRITE_ROLES, get_current_user, require_roles
from app.db.session import get_db
from app.models.cleanroom_v1 import GeoBusinessGoal, GeoOptimizationAction
from app.models.user import User
from app.models.workspace_access import WorkspaceMembership
from app.services.audit import record_audit_log
from app.services.workspace_access import require_workspace_access
from app.v1.results_roi import build_results_overview


router = APIRouter(prefix="/v1", tags=["geo-business-goals-v1"])


class BusinessGoalUpsert(BaseModel):
    title: str = Field(min_length=4, max_length=255)
    metric_key: Literal["shortlist_rate"] = "shortlist_rate"
    target_value: float = Field(gt=0, le=100)
    due_at: datetime
    owner_user_id: int | None = Field(default=None, ge=1)
    question_plan_ids: list[int] = Field(default_factory=list, max_length=50)
    model_keys: list[str] = Field(default_factory=list, max_length=20)
    action_ids: list[int] = Field(default_factory=list, max_length=50)
    period_days: int = Field(default=30, ge=7, le=365)
    batch_ids: list[int] = Field(default_factory=list, max_length=50)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("question_plan_ids", "action_ids", "batch_ids")
    @classmethod
    def normalize_ids(cls, value: list[int]) -> list[int]:
        if any(item < 1 for item in value):
            raise ValueError("范围 ID 必须为正整数")
        return sorted(set(value))

    @field_validator("model_keys")
    @classmethod
    def normalize_models(cls, value: list[str]) -> list[str]:
        normalized = sorted({item.strip().lower() for item in value if item.strip()})
        if any(len(item) > 120 for item in normalized):
            raise ValueError("模型标识过长")
        return normalized

    @model_validator(mode="after")
    def validate_due_at(self):
        due_at = self.due_at.replace(tzinfo=UTC) if self.due_at.tzinfo is None else self.due_at.astimezone(UTC)
        if due_at <= datetime.now(UTC):
            raise ValueError("目标截止时间必须晚于当前时间")
        self.due_at = due_at
        return self


def _scope(payload: BusinessGoalUpsert) -> dict:
    return {
        "period_days": payload.period_days,
        "batch_ids": payload.batch_ids,
        "model_keys": payload.model_keys,
        "question_plan_ids": payload.question_plan_ids,
        "metric_contract": "evidence-gated-shortlist-rate/v1",
    }


def _measurement(db: Session, workspace, scope: dict) -> tuple[float | None, float | None]:
    overview = build_results_overview(
        db,
        workspace,
        period_days=int(scope.get("period_days") or 30),
        model_keys=list(scope.get("model_keys") or []),
        question_plan_ids=list(scope.get("question_plan_ids") or []),
        batch_ids=list(scope.get("batch_ids") or []),
    )
    series = overview["effect"]["historical"]["series"]
    if not series:
        return None, None
    return float(series[0]["shortlist_rate"]), float(series[-1]["shortlist_rate"])


def _goal_read(db: Session, workspace, goal: GeoBusinessGoal) -> dict:
    baseline_from_series, current_value = _measurement(db, workspace, goal.scope_snapshot or {})
    baseline_value = goal.baseline_value
    if baseline_value is None:
        baseline_value = baseline_from_series
    progress_percent = None
    remaining_value = None
    if baseline_value is not None and current_value is not None:
        span = goal.target_value - baseline_value
        progress_percent = 100.0 if span <= 0 and current_value >= goal.target_value else (
            max(0.0, min(100.0, (current_value - baseline_value) / span * 100)) if span > 0 else 0.0
        )
        remaining_value = max(0.0, goal.target_value - current_value)
    owner = db.get(User, goal.owner_user_id) if goal.owner_user_id else None
    return {
        "id": goal.id,
        "workspace_id": goal.workspace_id,
        "title": goal.title,
        "metric_key": goal.metric_key,
        "metric_label": "候选进入率",
        "baseline_value": baseline_value,
        "current_value": current_value,
        "target_value": goal.target_value,
        "progress_percent": round(progress_percent, 1) if progress_percent is not None else None,
        "remaining_value": round(remaining_value, 1) if remaining_value is not None else None,
        "start_at": goal.start_at,
        "due_at": goal.due_at,
        "owner_user_id": goal.owner_user_id,
        "owner_name": owner.name if owner else None,
        "status": goal.status,
        "question_plan_ids": goal.question_plan_ids or [],
        "model_keys": goal.model_keys or [],
        "action_ids": goal.action_ids or [],
        "scope_snapshot": goal.scope_snapshot or {},
        "created_at": goal.created_at,
        "updated_at": goal.updated_at,
    }


@router.get("/workspaces/{workspace_id}/business-goal")
def read_business_goal(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace, _membership = require_workspace_access(db, user, workspace_id)
    goal = db.scalar(
        select(GeoBusinessGoal)
        .where(
            GeoBusinessGoal.workspace_id == workspace_id,
            GeoBusinessGoal.status == "active",
        )
        .order_by(GeoBusinessGoal.updated_at.desc(), GeoBusinessGoal.id.desc())
    )
    return _goal_read(db, workspace, goal) if goal else None


@router.put("/workspaces/{workspace_id}/business-goal")
def upsert_business_goal(
    workspace_id: int,
    payload: BusinessGoalUpsert,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace, _membership = require_workspace_access(db, user, workspace_id)
    if payload.owner_user_id is not None:
        owner = db.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == payload.owner_user_id,
                WorkspaceMembership.status == "active",
            )
        )
        if owner is None:
            raise HTTPException(status_code=422, detail="负责人不是当前工作区成员")
    if payload.action_ids:
        valid_action_ids = set(
            db.scalars(
                select(GeoOptimizationAction.id).where(
                    GeoOptimizationAction.workspace_id == workspace_id,
                    GeoOptimizationAction.id.in_(payload.action_ids),
                )
            )
        )
        if valid_action_ids != set(payload.action_ids):
            raise HTTPException(status_code=422, detail="目标包含不属于当前工作区的行动")

    scope_snapshot = _scope(payload)
    baseline_value, _current_value = _measurement(db, workspace, scope_snapshot)
    goal = db.scalar(
        select(GeoBusinessGoal).where(
            GeoBusinessGoal.workspace_id == workspace_id,
            GeoBusinessGoal.status == "active",
        )
    )
    now = datetime.now(UTC)
    created = goal is None
    if goal is None:
        goal = GeoBusinessGoal(
            workspace_id=workspace_id,
            title=payload.title,
            metric_key=payload.metric_key,
            baseline_value=baseline_value,
            target_value=payload.target_value,
            start_at=now,
            due_at=payload.due_at,
            owner_user_id=payload.owner_user_id,
            status="active",
            question_plan_ids=payload.question_plan_ids,
            model_keys=payload.model_keys,
            action_ids=payload.action_ids,
            scope_snapshot=scope_snapshot,
            created_by_user_id=user.id,
        )
        db.add(goal)
    else:
        scope_changed = (goal.scope_snapshot or {}) != scope_snapshot
        goal.title = payload.title
        goal.metric_key = payload.metric_key
        goal.target_value = payload.target_value
        goal.due_at = payload.due_at
        goal.owner_user_id = payload.owner_user_id
        goal.question_plan_ids = payload.question_plan_ids
        goal.model_keys = payload.model_keys
        goal.action_ids = payload.action_ids
        goal.scope_snapshot = scope_snapshot
        if scope_changed:
            goal.baseline_value = baseline_value
            goal.start_at = now

    db.flush()
    record_audit_log(
        db,
        user=user,
        action="geo.business_goal.created" if created else "geo.business_goal.updated",
        resource_type="geo_business_goal",
        resource_id=goal.id,
        company_id=workspace.company_id,
        detail={
            "workspace_id": workspace_id,
            "metric_key": goal.metric_key,
            "target_value": goal.target_value,
            "scope_snapshot": goal.scope_snapshot,
        },
    )
    db.commit()
    db.refresh(goal)
    return _goal_read(db, workspace, goal)
