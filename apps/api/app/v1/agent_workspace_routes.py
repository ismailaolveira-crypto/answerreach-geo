from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import WRITE_ROLES, get_current_user, require_roles
from app.core.config import get_settings
from app.db.session import get_db
from app.models.cleanroom_v1 import (
    GeoAgentConversation,
    GeoAgentConversationEvent,
    GeoAgentConversationMessage,
    GeoActionTarget,
    GeoObservationBatch,
    GeoOptimizationAction,
    GeoQuestionPlan,
)
from app.models.job import QueueJob
from app.models.user import User
from app.services.agent_runtime import RUNTIME_KEYS, diagnose_agent_runtime
from app.services.job_queue import (
    count_workspace_agent_reservations,
    geo_job_payload,
    user_visible_job_error,
)
from app.services.workspace_access import require_workspace_access
from app.v1.action_workflow import (
    MANAGER_ROLES,
    append_event,
    assert_active_member,
    canonical_fingerprint,
    utcnow,
    workspace_role,
)
from app.v1.agent_workspace import _trusted_context


router = APIRouter(prefix="/v1", tags=["geo-agent-workspace-v1"])


class ConversationContext(BaseModel):
    batch_id: int | None = Field(default=None, ge=1)
    question_plan_id: int | None = Field(default=None, ge=1)
    action_id: int | None = Field(default=None, ge=1)
    model_keys: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("model_keys")
    @classmethod
    def normalize_models(cls, value: list[str]) -> list[str]:
        return sorted({item.strip().lower() for item in value if item.strip()})


class ConversationCreate(BaseModel):
    title: str = Field(default="新的 GEO 对话", min_length=1, max_length=160)
    context: ConversationContext = Field(default_factory=ConversationContext)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    status: Literal["active", "archived"] | None = None
    context: ConversationContext | None = None


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    runtime_key: str = "auto"
    model: str | None = Field(default=None, max_length=120)
    reasoning_effort: Literal["low", "medium", "high", "xhigh"] | None = None

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("消息不能为空")
        return normalized


class SuggestionActionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    expected_goal: str = Field(min_length=1, max_length=3000)
    assignee_user_id: int = Field(ge=1)
    due_at: datetime


def _conversation_or_404(
    db: Session, workspace_id: int, conversation_id: int, user_id: int
) -> GeoAgentConversation:
    conversation = db.scalar(
        select(GeoAgentConversation).where(
            GeoAgentConversation.id == conversation_id,
            GeoAgentConversation.workspace_id == workspace_id,
            GeoAgentConversation.created_by_user_id == user_id,
        )
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Agent 对话不存在")
    return conversation


def _validated_context(db: Session, workspace_id: int, context: ConversationContext) -> dict:
    if context.batch_id:
        item = db.get(GeoObservationBatch, context.batch_id)
        if item is None or item.workspace_id != workspace_id:
            raise HTTPException(status_code=422, detail="观测批次不属于当前工作区")
    if context.question_plan_id:
        item = db.get(GeoQuestionPlan, context.question_plan_id)
        if item is None or item.workspace_id != workspace_id:
            raise HTTPException(status_code=422, detail="问题不属于当前工作区")
    if context.action_id:
        item = db.get(GeoOptimizationAction, context.action_id)
        if item is None or item.workspace_id != workspace_id:
            raise HTTPException(status_code=422, detail="优化行动不属于当前工作区")
    return context.model_dump()


def _event_read(event: GeoAgentConversationEvent) -> dict:
    return {
        "id": event.id,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "stage": event.stage,
        "message": event.message,
        "detail": event.detail or {},
        "created_at": event.created_at,
    }


def _effective_message_state(
    db: Session, message: GeoAgentConversationMessage
) -> tuple[str, str | None]:
    if message.job_id and message.status in {"queued", "running"}:
        job = db.get(QueueJob, message.job_id)
        if job is not None and job.status == "failed":
            return "failed", message.error_message or user_visible_job_error(job)
    return message.status, message.error_message


def _message_read(db: Session, message: GeoAgentConversationMessage) -> dict:
    events = list(
        db.scalars(
            select(GeoAgentConversationEvent)
            .where(GeoAgentConversationEvent.message_id == message.id)
            .order_by(GeoAgentConversationEvent.sequence.asc())
        )
    )
    status, error_message = _effective_message_state(db, message)
    return {
        "id": message.id,
        "sequence": message.sequence,
        "role": message.role,
        "content": message.content,
        "status": status,
        "structured_payload": message.structured_payload or {},
        "runtime_key": message.runtime_key,
        "model": message.model,
        "job_id": message.job_id,
        "error_message": error_message,
        "events": [_event_read(item) for item in events],
        "created_at": message.created_at,
        "updated_at": message.updated_at,
    }


def _conversation_read(db: Session, conversation: GeoAgentConversation, include_messages: bool = False) -> dict:
    messages = []
    if include_messages:
        messages = list(
            db.scalars(
                select(GeoAgentConversationMessage)
                .where(GeoAgentConversationMessage.conversation_id == conversation.id)
                .order_by(GeoAgentConversationMessage.sequence.asc())
            )
        )
    latest = db.scalar(
        select(GeoAgentConversationMessage)
        .where(GeoAgentConversationMessage.conversation_id == conversation.id)
        .order_by(GeoAgentConversationMessage.sequence.desc())
        .limit(1)
    )
    latest_status = _effective_message_state(db, latest)[0] if latest else None
    return {
        "id": conversation.id,
        "workspace_id": conversation.workspace_id,
        "title": conversation.title,
        "status": conversation.status,
        "runtime_key": conversation.runtime_key,
        "model": conversation.model,
        "reasoning_effort": conversation.reasoning_effort,
        "context": conversation.context_snapshot or {},
        "last_message_status": latest_status,
        "needs_user": bool((latest.structured_payload or {}).get("needs_user")) if latest else False,
        "last_message_at": conversation.last_message_at,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
        "messages": [_message_read(db, item) for item in messages],
    }


@router.get("/workspaces/{workspace_id}/agent-workspace/context-options")
def read_agent_workspace_context_options(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_workspace_access(db, user, workspace_id)
    batches = list(
        db.scalars(
            select(GeoObservationBatch)
            .where(GeoObservationBatch.workspace_id == workspace_id)
            .order_by(GeoObservationBatch.id.desc())
            .limit(30)
        )
    )
    questions = list(
        db.scalars(
            select(GeoQuestionPlan)
            .where(GeoQuestionPlan.workspace_id == workspace_id, GeoQuestionPlan.active.is_(True))
            .order_by(GeoQuestionPlan.updated_at.desc())
            .limit(100)
        )
    )
    actions = list(
        db.scalars(
            select(GeoOptimizationAction)
            .where(GeoOptimizationAction.workspace_id == workspace_id)
            .order_by(GeoOptimizationAction.updated_at.desc())
            .limit(100)
        )
    )
    return {
        "batches": [
            {"id": item.id, "label": f"批次 #{item.id}", "status": item.status, "model_keys": list((item.configuration or {}).get("model_keys") or [])}
            for item in batches
        ],
        "questions": [{"id": item.id, "label": item.question_text} for item in questions],
        "actions": [{"id": item.id, "label": item.title, "status": item.status} for item in actions],
    }


@router.get("/workspaces/{workspace_id}/agent-workspace/conversations")
def list_agent_workspace_conversations(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_workspace_access(db, user, workspace_id)
    conversations = list(
        db.scalars(
            select(GeoAgentConversation)
            .where(
                GeoAgentConversation.workspace_id == workspace_id,
                GeoAgentConversation.created_by_user_id == user.id,
                GeoAgentConversation.status == "active",
            )
            .order_by(
                GeoAgentConversation.last_message_at.desc().nullslast(),
                GeoAgentConversation.id.desc(),
            )
        )
    )
    return [_conversation_read(db, item) for item in conversations]


@router.post("/workspaces/{workspace_id}/agent-workspace/conversations", status_code=201)
def create_agent_workspace_conversation(
    workspace_id: int,
    payload: ConversationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    require_workspace_access(db, user, workspace_id)
    conversation = GeoAgentConversation(
        workspace_id=workspace_id,
        created_by_user_id=user.id,
        title=payload.title.strip(),
        context_snapshot=_validated_context(db, workspace_id, payload.context),
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return _conversation_read(db, conversation, include_messages=True)


@router.get("/workspaces/{workspace_id}/agent-workspace/conversations/{conversation_id}")
def read_agent_workspace_conversation(
    workspace_id: int,
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_workspace_access(db, user, workspace_id)
    return _conversation_read(
        db, _conversation_or_404(db, workspace_id, conversation_id, user.id), include_messages=True
    )


@router.patch("/workspaces/{workspace_id}/agent-workspace/conversations/{conversation_id}")
def update_agent_workspace_conversation(
    workspace_id: int,
    conversation_id: int,
    payload: ConversationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    require_workspace_access(db, user, workspace_id)
    conversation = _conversation_or_404(db, workspace_id, conversation_id, user.id)
    if payload.title is not None:
        conversation.title = payload.title.strip()
    if payload.status is not None:
        conversation.status = payload.status
    if payload.context is not None:
        conversation.context_snapshot = _validated_context(db, workspace_id, payload.context)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return _conversation_read(db, conversation, include_messages=True)


@router.post(
    "/workspaces/{workspace_id}/agent-workspace/conversations/{conversation_id}/messages",
    status_code=202,
)
def create_agent_workspace_message(
    workspace_id: int,
    conversation_id: int,
    payload: MessageCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace, _membership = require_workspace_access(db, user, workspace_id)
    conversation = _conversation_or_404(db, workspace_id, conversation_id, user.id)
    if conversation.status != "active":
        raise HTTPException(status_code=409, detail="已归档的对话不能继续发送")
    active_queue_statuses = ["pending", "running", "recovering"]
    active_in_conversation = int(
        db.scalar(
            select(func.count())
            .select_from(GeoAgentConversationMessage)
            .outerjoin(QueueJob, QueueJob.id == GeoAgentConversationMessage.job_id)
            .where(
                GeoAgentConversationMessage.conversation_id == conversation.id,
                GeoAgentConversationMessage.status.in_(["queued", "running"]),
                or_(
                    GeoAgentConversationMessage.job_id.is_(None),
                    QueueJob.status.in_(active_queue_statuses),
                ),
            )
        )
        or 0
    )
    if active_in_conversation:
        raise HTTPException(status_code=409, detail="这段对话仍在处理中")
    limit = max(1, min(int(get_settings().agent_max_concurrent_runs), 10))
    if count_workspace_agent_reservations(db, workspace_id) >= limit:
        raise HTTPException(status_code=409, detail=f"Agent 当前容量已满（{limit} 个并行任务）")

    runtime_key = payload.runtime_key
    if runtime_key == "auto":
        runtime_key = next(
            (key for key in ("local_codex", "hermes", "claude_agent", "openclaw") if diagnose_agent_runtime(key).get("ready")),
            "",
        )
    if runtime_key not in RUNTIME_KEYS:
        raise HTTPException(status_code=422, detail="没有可用的 Agent 运行时")
    diagnostic = diagnose_agent_runtime(runtime_key)
    if not diagnostic.get("ready"):
        raise HTTPException(status_code=409, detail=diagnostic.get("error") or "所选 Agent 尚未就绪")
    available_models = list(diagnostic.get("available_models") or [])
    model = payload.model or diagnostic.get("default_model")
    if model and available_models and model not in available_models:
        raise HTTPException(status_code=422, detail="所选模型不可用")

    next_sequence = int(
        db.scalar(
            select(func.coalesce(func.max(GeoAgentConversationMessage.sequence), 0)).where(
                GeoAgentConversationMessage.conversation_id == conversation.id
            )
        )
        or 0
    ) + 1
    now = datetime.now(UTC)
    user_message = GeoAgentConversationMessage(
        workspace_id=workspace_id,
        conversation_id=conversation.id,
        sequence=next_sequence,
        role="user",
        content=payload.content,
        status="completed",
        created_by_user_id=user.id,
    )
    assistant_message = GeoAgentConversationMessage(
        workspace_id=workspace_id,
        conversation_id=conversation.id,
        sequence=next_sequence + 1,
        role="assistant",
        content=payload.content,
        status="queued",
        runtime_key=runtime_key,
        model=model,
    )
    if conversation.title == "新的 GEO 对话":
        conversation.title = payload.content[:32]
    if conversation.runtime_key != runtime_key:
        conversation.external_thread_id = None
    conversation.runtime_key = runtime_key
    conversation.model = model
    conversation.reasoning_effort = payload.reasoning_effort or diagnostic.get("default_reasoning_effort")
    conversation.last_message_at = now
    db.add_all([conversation, user_message, assistant_message])
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="这段对话仍在处理中") from None
    job = QueueJob(
        job_type="geo_agent.conversation",
        status="pending",
        priority=10,
        max_attempts=1,
        scheduled_at=now,
        payload_json=geo_job_payload(
            workspace_id=workspace_id,
            company_id=workspace.company_id,
            actor_user_id=user.id,
            conversation_id=conversation.id,
            message_id=assistant_message.id,
        ),
    )
    db.add(job)
    db.flush()
    assistant_message.job_id = job.id
    db.add(assistant_message)
    db.commit()
    db.refresh(conversation)
    return _conversation_read(db, conversation, include_messages=True)


@router.post(
    "/workspaces/{workspace_id}/agent-workspace/conversations/{conversation_id}/messages/{message_id}/action",
    status_code=201,
)
def create_agent_suggestion_action(
    workspace_id: int,
    conversation_id: int,
    message_id: int,
    payload: SuggestionActionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    membership = workspace_role(db, user, workspace_id)
    conversation = _conversation_or_404(db, workspace_id, conversation_id, user.id)
    message = db.get(GeoAgentConversationMessage, message_id)
    if (
        message is None
        or message.workspace_id != workspace_id
        or message.conversation_id != conversation.id
        or message.role != "assistant"
        or message.status != "completed"
    ):
        raise HTTPException(status_code=404, detail="Agent 建议不存在")
    message_payload = dict(message.structured_payload or {})
    suggestion = message_payload.get("suggested_action")
    if not isinstance(suggestion, dict):
        raise HTTPException(status_code=409, detail="这条回答没有可创建的优化行动")
    linked_action_id = message_payload.get("linked_action_id")
    linked_action = db.get(GeoOptimizationAction, linked_action_id) if linked_action_id else None
    if linked_action and linked_action.workspace_id == workspace_id:
        return {"action_id": linked_action.id, "created": False}

    assignee = assert_active_member(db, workspace_id, payload.assignee_user_id)
    if assignee.role == "viewer":
        raise HTTPException(status_code=422, detail="只读成员不能承接优化行动")
    if user.role != "super_admin" and not (
        membership and membership.role in MANAGER_ROLES
    ) and payload.assignee_user_id != user.id:
        raise HTTPException(status_code=403, detail="只有管理员可以指派给其他成员")
    due_at = payload.due_at if payload.due_at.tzinfo else payload.due_at.replace(tzinfo=UTC)
    if due_at <= utcnow():
        raise HTTPException(status_code=422, detail="截止时间必须晚于当前时间")

    source_context = message_payload.get("source_context")
    if not isinstance(source_context, dict):
        trusted = _trusted_context(db, conversation)
        source_context = {
            "scope": trusted["scope"],
            "evidence_ids": [item["id"] for item in trusted["evidence"]],
            "evidence_count": trusted["evidence_count"],
        }
    scope = dict(source_context.get("scope") or conversation.context_snapshot or {})
    evidence_ids = [int(value) for value in source_context.get("evidence_ids") or [] if str(value).isdigit()]
    question_id = int(scope["question_plan_id"]) if scope.get("question_plan_id") else None
    model_keys = sorted({str(value).strip().lower() for value in scope.get("model_keys") or [] if str(value).strip()})
    action = GeoOptimizationAction(
        workspace_id=workspace_id,
        question_plan_id=question_id,
        source_evidence_id=evidence_ids[0] if evidence_ids else None,
        title=payload.title.strip(),
        rationale=str(suggestion.get("summary") or message.content).strip(),
        hypothesis=payload.expected_goal.strip(),
        priority="medium",
        status="in_progress",
        stage="accepted",
        baseline_snapshot={
            "source": "agent_workspace",
            "conversation_id": conversation.id,
            "message_id": message.id,
            "evidence_ids": evidence_ids,
        },
        selected_scope=scope,
        measurement_plan={"status": "not_eligible", "source": "agent_workspace"},
        action_type="analysis",
        deliverable_type="analysis_report",
        workflow_version="action-flow.v2",
        assignee_user_id=payload.assignee_user_id,
        due_at=due_at,
        affected_question_ids=[question_id] if question_id else [],
        affected_model_keys=model_keys,
        scope_fingerprint=canonical_fingerprint(
            {"conversation_id": conversation.id, "message_id": message.id, "scope": scope}
        ),
        measurement_status="not_eligible",
        selected_at=utcnow(),
    )
    db.add(action)
    db.flush()
    db.add(
        GeoActionTarget(
            workspace_id=workspace_id,
            action_id=action.id,
            target_key=f"agent-message:{message.id}:analysis",
            target_type="analysis_deliverable",
            display_name="分析报告",
            target_ref=payload.title.strip(),
            delivery_status="scope_confirmed",
            ordinal=0,
            metadata_json={
                "source": "agent_workspace",
                "conversation_id": conversation.id,
                "message_id": message.id,
            },
        )
    )
    append_event(
        db,
        action=action,
        event_type="agent_recommendation_created",
        actor_user_id=user.id,
        from_stage=None,
        to_stage="accepted",
        detail={"conversation_id": conversation.id, "message_id": message.id},
    )
    message_payload["linked_action_id"] = action.id
    message.structured_payload = message_payload
    db.add(message)
    db.commit()
    return {"action_id": action.id, "created": True}
