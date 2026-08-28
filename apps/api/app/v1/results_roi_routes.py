from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import WRITE_ROLES, get_current_user, require_roles
from app.db.session import get_db
from app.models.cleanroom_v1 import (
    GeoBusinessMetricEntry,
    GeoOptimizationAction,
)
from app.models.user import User
from app.services.audit import record_audit_log
from app.services.workspace_access import require_workspace_access
from app.v1.results_roi import (
    COST_METRICS,
    MONEY_METRICS,
    QUANTITY_METRICS,
    build_results_overview,
)


router = APIRouter(prefix="/v1", tags=["geo-results-roi"])


class BusinessMetricCreate(BaseModel):
    action_id: int | None = Field(default=None, ge=1)
    metric_type: Literal[
        "content_cost",
        "labor_cost",
        "distribution_cost",
        "tool_cost",
        "ai_referral_visit",
        "qualified_lead",
        "sales_opportunity",
        "pipeline_value",
        "won_revenue",
    ]
    amount: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    quantity: float | None = Field(default=None, ge=0, le=1_000_000_000)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    attribution_type: Literal["direct", "assisted", "unallocated", "not_applicable"] = (
        "not_applicable"
    )
    source_type: Literal["manual", "manual_import", "analytics", "crm", "finance"] = "manual"
    source_label: str = Field(min_length=2, max_length=255)
    source_reference: str | None = Field(default=None, max_length=1500)
    evidence_note: str = Field(min_length=4, max_length=4000)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=80)

    @model_validator(mode="after")
    def validate_metric_contract(self):
        if self.metric_type in MONEY_METRICS:
            if self.amount is None:
                raise ValueError("金额类记录必须填写金额")
            if not self.currency:
                raise ValueError("金额类记录必须填写币种")
            self.currency = self.currency.upper()
            self.quantity = None
        elif self.metric_type in QUANTITY_METRICS:
            if self.quantity is None:
                raise ValueError("数量类记录必须填写数量")
            self.amount = None
            self.currency = None
        if self.metric_type in COST_METRICS and self.attribution_type != "not_applicable":
            raise ValueError("成本记录不使用收入归因类型")
        if self.metric_type in QUANTITY_METRICS and self.attribution_type == "not_applicable":
            raise ValueError("访问和线索必须标明直接、辅助或未分配归因")
        if self.metric_type == "won_revenue" and self.attribution_type not in {
            "direct",
            "assisted",
            "unallocated",
        }:
            raise ValueError("成交收入必须标明直接、辅助或未分配归因")
        if self.metric_type == "won_revenue" and self.attribution_type == "direct":
            if self.action_id is None:
                raise ValueError("直接成交必须关联具体优化行动")
            if self.source_type not in {"crm", "finance"} or not self.source_reference:
                raise ValueError("直接成交必须提供 CRM/财务来源和凭证编号")
        return self


class BusinessMetricReverse(BaseModel):
    reason: str = Field(min_length=4, max_length=1000)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=80)


@router.get("/workspaces/{workspace_id}/results-overview")
def read_results_overview(
    workspace_id: int,
    period_days: int = Query(default=30, ge=7, le=365),
    model_key: str | None = Query(default=None, min_length=1, max_length=120),
    model_keys: list[str] | None = Query(default=None),
    question_plan_id: int | None = Query(default=None, ge=1),
    question_plan_ids: list[int] | None = Query(default=None),
    batch_ids: list[int] | None = Query(default=None),
    roi_action_ids: list[int] | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace, _membership = require_workspace_access(db, user, workspace_id)
    selected_question_ids = sorted({item for item in (question_plan_ids or []) if item > 0})
    if len(selected_question_ids) > 50:
        raise HTTPException(status_code=422, detail="问题范围最多选择 50 个问题")
    selected_roi_action_ids = sorted({item for item in (roi_action_ids or []) if item > 0})
    if len(selected_roi_action_ids) > 50:
        raise HTTPException(status_code=422, detail="ROI 行动范围最多选择 50 个行动")
    selected_model_keys = sorted({item.strip() for item in (model_keys or []) if item.strip()})
    if model_key and model_key not in selected_model_keys:
        selected_model_keys.append(model_key)
    if len(selected_model_keys) > 20:
        raise HTTPException(status_code=422, detail="模型范围最多选择 20 个模型")
    selected_batch_ids = sorted({item for item in (batch_ids or []) if item > 0})
    if len(selected_batch_ids) > 100:
        raise HTTPException(status_code=422, detail="批次范围最多选择 100 个批次")
    return build_results_overview(
        db,
        workspace,
        period_days=period_days,
        model_key=model_key,
        model_keys=selected_model_keys,
        question_plan_id=question_plan_id,
        question_plan_ids=selected_question_ids,
        batch_ids=selected_batch_ids,
        roi_action_ids=selected_roi_action_ids,
    )


@router.post(
    "/workspaces/{workspace_id}/business-metrics",
    status_code=status.HTTP_201_CREATED,
)
def create_business_metric(
    workspace_id: int,
    payload: BusinessMetricCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace, _membership = require_workspace_access(db, user, workspace_id)
    if payload.action_id is not None:
        action = db.get(GeoOptimizationAction, payload.action_id)
        if action is None or action.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="关联行动不存在")
    key = payload.idempotency_key or uuid4().hex
    existing = db.scalar(
        select(GeoBusinessMetricEntry).where(
            GeoBusinessMetricEntry.workspace_id == workspace_id,
            GeoBusinessMetricEntry.idempotency_key == key,
        )
    )
    if existing is not None:
        return {"id": existing.id, "status": "already_recorded"}
    amount_minor = None
    if payload.amount is not None:
        amount_minor = int(
            (payload.amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
    row = GeoBusinessMetricEntry(
        workspace_id=workspace_id,
        action_id=payload.action_id,
        metric_type=payload.metric_type,
        amount_minor=amount_minor,
        quantity=payload.quantity,
        currency=payload.currency,
        attribution_type=payload.attribution_type,
        source_type=payload.source_type,
        source_label=payload.source_label.strip(),
        source_reference=payload.source_reference.strip() if payload.source_reference else None,
        evidence_note=payload.evidence_note.strip(),
        verification_status="user_confirmed",
        occurred_at=payload.occurred_at,
        created_by_user_id=user.id,
        idempotency_key=key,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        duplicate = db.scalar(
            select(GeoBusinessMetricEntry).where(
                GeoBusinessMetricEntry.workspace_id == workspace_id,
                GeoBusinessMetricEntry.idempotency_key == key,
            )
        )
        if duplicate is None:
            raise
        return {"id": duplicate.id, "status": "already_recorded"}
    record_audit_log(
        db,
        user=user,
        action="geo.business_metric.recorded",
        resource_type="geo_business_metric",
        resource_id=row.id,
        company_id=workspace.company_id,
        detail={
            "workspace_id": workspace_id,
            "action_id": row.action_id,
            "metric_type": row.metric_type,
            "source_type": row.source_type,
            "verification_status": row.verification_status,
        },
    )
    db.commit()
    return {"id": row.id, "status": "recorded"}


@router.post(
    "/workspaces/{workspace_id}/business-metrics/{entry_id}/reverse",
    status_code=status.HTTP_201_CREATED,
)
def reverse_business_metric(
    workspace_id: int,
    entry_id: int,
    payload: BusinessMetricReverse,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace, _membership = require_workspace_access(db, user, workspace_id)
    original = db.get(GeoBusinessMetricEntry, entry_id)
    if original is None or original.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="业务记录不存在")
    if original.reverses_entry_id is not None:
        raise HTTPException(status_code=409, detail="冲销记录不能再次冲销")
    existing = db.scalar(
        select(GeoBusinessMetricEntry).where(
            GeoBusinessMetricEntry.reverses_entry_id == original.id
        )
    )
    if existing is not None:
        return {"id": existing.id, "status": "already_reversed"}
    row = GeoBusinessMetricEntry(
        workspace_id=workspace_id,
        action_id=original.action_id,
        metric_type=original.metric_type,
        amount_minor=-original.amount_minor if original.amount_minor is not None else None,
        quantity=-original.quantity if original.quantity is not None else None,
        currency=original.currency,
        attribution_type=original.attribution_type,
        source_type="system",
        source_label=f"冲销记录 #{original.id}",
        source_reference=original.source_reference,
        evidence_note=f"冲销原因：{payload.reason.strip()}",
        verification_status="system_verified",
        occurred_at=datetime.now(timezone.utc),
        created_by_user_id=user.id,
        idempotency_key=payload.idempotency_key or uuid4().hex,
        reverses_entry_id=original.id,
        reversal_reason=payload.reason.strip(),
    )
    db.add(row)
    db.flush()
    record_audit_log(
        db,
        user=user,
        action="geo.business_metric.reversed",
        resource_type="geo_business_metric",
        resource_id=row.id,
        company_id=workspace.company_id,
        detail={"workspace_id": workspace_id, "reverses_entry_id": original.id},
    )
    db.commit()
    return {"id": row.id, "status": "reversed"}
