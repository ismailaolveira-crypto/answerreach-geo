from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.cleanroom_v1 import (
    GeoEvidence,
    GeoObservationBatch,
    GeoObservationTask,
    GeoQuestionPlan,
)
from app.models.user import User
from app.services.workspace_access import require_workspace_access


router = APIRouter(prefix="/v1", tags=["geo-global-scope-v1"])

ScopePreset = Literal["7d", "30d", "90d", "365d", "custom"]
VALID_PRESETS: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90, "365d": 365}
MAX_BATCHES = 100
MAX_MODELS = 20
MAX_QUESTIONS = 100


class GeoGlobalScopeRead(BaseModel):
    version: Literal[1] = 1
    workspace_id: int
    range: ScopePreset
    date_from: date
    date_to: date
    batch_ids: list[int] = Field(default_factory=list, max_length=MAX_BATCHES)
    model_keys: list[str] = Field(default_factory=list, max_length=MAX_MODELS)
    question_plan_ids: list[int] = Field(default_factory=list, max_length=MAX_QUESTIONS)
    mode: Literal["single", "historical"]
    fingerprint: str


class GlobalScopeBatchOption(BaseModel):
    id: int
    label: str
    status: str
    source_type: str
    created_at: datetime
    completed_at: datetime | None
    provider_count: int
    question_count: int
    model_keys: list[str]
    question_plan_ids: list[int]


class GlobalScopeModelOption(BaseModel):
    key: str
    label: str
    logo_key: str | None = None
    observation_count: int = 0


class GlobalScopeQuestionOption(BaseModel):
    id: int
    label: str
    importance: int
    journey_stage: str


class GeoGlobalScopeOptionsRead(BaseModel):
    scope: GeoGlobalScopeRead
    batches: list[GlobalScopeBatchOption]
    models: list[GlobalScopeModelOption]
    questions: list[GlobalScopeQuestionOption]
    corrections: list[str] = Field(default_factory=list)
    capabilities: dict[str, bool]


def _dedupe_ints(values: list[int], *, limit: int) -> list[int]:
    return sorted(set(value for value in values if value > 0))[:limit]


def _dedupe_strings(values: list[str], *, limit: int) -> list[str]:
    return sorted(set(value.strip() for value in values if value.strip()))[:limit]


def _resolve_dates(
    range_value: str | None,
    date_from: date | None,
    date_to: date | None,
    legacy_period: int | None,
    *,
    today: date | None = None,
) -> tuple[ScopePreset, date, date, list[str]]:
    today = today or datetime.now(timezone.utc).date()
    corrections: list[str] = []
    preset = range_value if range_value in {*VALID_PRESETS, "custom"} else None
    if preset is None and legacy_period in set(VALID_PRESETS.values()):
        preset = f"{legacy_period}d"
    if preset is None:
        if range_value:
            corrections.append("无法识别的时间范围已改为最近 30 天")
        preset = "30d"

    if preset == "custom":
        if date_from is None or date_to is None or date_from > date_to or date_to > today:
            corrections.append("自定义日期无效，已改为最近 30 天")
            preset = "30d"
        else:
            return "custom", date_from, date_to, corrections

    days = VALID_PRESETS[preset]
    return preset, today - timedelta(days=days - 1), today, corrections


def _scope_fingerprint(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def _batch_label(batch: GeoObservationBatch) -> str:
    created = batch.created_at
    date_label = created.astimezone(timezone.utc).strftime("%m/%d") if created else "--/--"
    return f"批次 #{batch.id} · {date_label}"


@router.get(
    "/workspaces/{workspace_id}/global-scope-options",
    response_model=GeoGlobalScopeOptionsRead,
)
def get_global_scope_options(
    workspace_id: int,
    range_value: Annotated[str | None, Query(alias="range")] = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    batch_ids: Annotated[list[int] | None, Query(alias="batch")] = None,
    model_keys: Annotated[list[str] | None, Query(alias="model")] = None,
    question_plan_ids: Annotated[list[int] | None, Query(alias="question")] = None,
    legacy_period: Annotated[int | None, Query(alias="period")] = None,
    legacy_period_days: Annotated[int | None, Query(alias="period_days")] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GeoGlobalScopeOptionsRead:
    require_workspace_access(db, user, workspace_id)
    preset, resolved_from, resolved_to, corrections = _resolve_dates(
        range_value,
        date_from,
        date_to,
        legacy_period_days or legacy_period,
    )

    batches = list(
        db.scalars(
            select(GeoObservationBatch)
            .where(
                GeoObservationBatch.workspace_id == workspace_id,
                GeoObservationBatch.status.in_(("completed", "partial", "success")),
            )
            .order_by(GeoObservationBatch.created_at.desc(), GeoObservationBatch.id.desc())
            .limit(MAX_BATCHES)
        )
    )
    batch_id_set = {batch.id for batch in batches}
    requested_batches = _dedupe_ints(batch_ids or [], limit=MAX_BATCHES)
    selected_batch_ids = [value for value in requested_batches if value in batch_id_set]
    removed_batches = sorted(set(requested_batches) - set(selected_batch_ids))
    if removed_batches:
        corrections.append(f"已移除 {len(removed_batches)} 个无效或不属于当前工作区的批次")
    if not requested_batches:
        selectable = [batch.id for batch in batches if batch.status in {"completed", "success", "partial"}]
        selected_batch_ids = selectable[:3] or [batch.id for batch in batches[:3]]

    tasks = list(
        db.scalars(
            select(GeoObservationTask)
            .where(GeoObservationTask.workspace_id == workspace_id)
            .order_by(GeoObservationTask.id.desc())
        )
    )
    selected_tasks = [
        task for task in tasks if not selected_batch_ids or task.batch_id in selected_batch_ids
    ]

    model_meta: dict[str, dict[str, str | int | None]] = {}
    for task in tasks:
        item = model_meta.setdefault(
            task.model_key,
            {
                "key": task.model_key,
                "label": task.model_label or task.model_key,
                "logo_key": task.model_key.lower(),
                "observation_count": 0,
            },
        )
        item["observation_count"] = int(item["observation_count"] or 0) + 1
    if not model_meta:
        for key, label in db.execute(
            select(distinct(GeoEvidence.model_key), GeoEvidence.model_label).where(
                GeoEvidence.workspace_id == workspace_id
            )
        ):
            model_meta[str(key)] = {
                "key": str(key),
                "label": str(label or key),
                "logo_key": str(key).lower(),
                "observation_count": 0,
            }
    available_models = {task.model_key for task in selected_tasks} or set(model_meta)
    requested_models = _dedupe_strings(model_keys or [], limit=MAX_MODELS)
    selected_models = [value for value in requested_models if value in available_models]
    removed_models = sorted(set(requested_models) - set(selected_models))
    if removed_models:
        corrections.append(f"已移除 {len(removed_models)} 个当前范围内不可用的模型")
    if not requested_models:
        selected_models = sorted(available_models)[:MAX_MODELS]

    questions = list(
        db.scalars(
            select(GeoQuestionPlan)
            .where(
                GeoQuestionPlan.workspace_id == workspace_id,
                GeoQuestionPlan.active.is_(True),
                GeoQuestionPlan.status.in_(("approved", "active")),
            )
            .order_by(
                GeoQuestionPlan.importance.desc(),
                GeoQuestionPlan.updated_at.desc(),
                GeoQuestionPlan.id.asc(),
            )
            .limit(MAX_QUESTIONS)
        )
    )
    all_question_ids = {question.id for question in questions}
    task_question_ids = {task.question_plan_id for task in selected_tasks}
    available_question_ids = (task_question_ids & all_question_ids) or all_question_ids
    requested_questions = _dedupe_ints(question_plan_ids or [], limit=MAX_QUESTIONS)
    selected_questions = [value for value in requested_questions if value in available_question_ids]
    removed_questions = sorted(set(requested_questions) - set(selected_questions))
    if removed_questions:
        corrections.append(f"已移除 {len(removed_questions)} 个已停用或不属于当前工作区的问题")
    if not requested_questions:
        selected_questions = [
            question.id for question in questions if not task_question_ids or question.id in task_question_ids
        ][:MAX_QUESTIONS]

    canonical_payload = {
        "version": 1,
        "workspaceId": workspace_id,
        "period": {
            "preset": preset,
            "dateFrom": resolved_from.isoformat(),
            "dateTo": resolved_to.isoformat(),
        },
        "batchIds": selected_batch_ids,
        "modelKeys": selected_models,
        "questionPlanIds": selected_questions,
        "mode": "historical" if len(selected_batch_ids) > 1 else "single",
    }
    scope = GeoGlobalScopeRead(
        workspace_id=workspace_id,
        range=preset,
        date_from=resolved_from,
        date_to=resolved_to,
        batch_ids=selected_batch_ids,
        model_keys=selected_models,
        question_plan_ids=selected_questions,
        mode=canonical_payload["mode"],
        fingerprint=_scope_fingerprint(canonical_payload),
    )
    batch_tasks: dict[int, list[GeoObservationTask]] = {}
    for task in tasks:
        batch_tasks.setdefault(task.batch_id, []).append(task)
    return GeoGlobalScopeOptionsRead(
        scope=scope,
        batches=[
            GlobalScopeBatchOption(
                id=batch.id,
                label=_batch_label(batch),
                status=batch.status,
                source_type=batch.source_type,
                created_at=batch.created_at,
                completed_at=batch.completed_at,
                provider_count=batch.provider_count,
                question_count=batch.question_count,
                model_keys=sorted({task.model_key for task in batch_tasks.get(batch.id, [])}),
                question_plan_ids=sorted(
                    {task.question_plan_id for task in batch_tasks.get(batch.id, [])}
                ),
            )
            for batch in batches
        ],
        models=[GlobalScopeModelOption(**value) for value in model_meta.values()],
        questions=[
            GlobalScopeQuestionOption(
                id=question.id,
                label=question.question_text,
                importance=question.importance,
                journey_stage=question.journey_stage,
            )
            for question in questions
        ],
        corrections=corrections,
        capabilities={
            "time": True,
            "batches": True,
            "models": True,
            "questions": True,
            "shareable_url": True,
        },
    )
