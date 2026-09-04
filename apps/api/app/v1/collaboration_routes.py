from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
import re
import shutil
from typing import Literal
from urllib.parse import unquote
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, HttpUrl, SecretStr, model_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.cleanroom_v1 import (
    GeoActionApproval,
    GeoActionCompletionEvidence,
    GeoActionEvent,
    GeoActionTarget,
    GeoChangeAlert,
    GeoContentAsset,
    GeoEvidence,
    GeoOptimizationAction,
    GeoQuestionPlan,
    GeoWorkspace,
)
from app.models.collaboration import (
    GeoCollaborationAttachment,
    GeoCollaborationChannel,
    GeoCollaborationDelivery,
    GeoCollaborationMemberBinding,
    GeoCollaborationMessage,
    GeoCollaborationMention,
    GeoCollaborationNotificationPreference,
    GeoCollaborationRead,
    GeoCollaborationThread,
)
from app.models.user import User
from app.models.workspace_access import WorkspaceMembership
from app.core.config import get_settings
from app.services.auth import consume_security_rate_limit
from app.services.workspace_access import require_workspace_access, require_workspace_manager
from app.services.workspace_secrets import get_workspace_secret, set_workspace_secret
from app.services.office_collaboration import (
    CAPABILITIES,
    PROVIDER_LABELS,
    OfficeProviderError,
    required_fields,
    send_message as send_office_message,
    test_connection as test_office_connection,
    validate_configuration,
    verify_member as verify_office_member,
)
from app.v1.action_workflow import TARGET_WORKFLOWS, append_event


router = APIRouter(prefix="/v1", tags=["collaboration-center"])

CONTEXT_TYPES = {"action", "alert", "question", "evidence"}
CHANNEL_PROVIDERS = {"wecom", "feishu", "dingtalk"}
CHANNEL_LABELS = {"wecom": "企业微信", "feishu": "飞书", "dingtalk": "钉钉"}
ACTION_TYPE_LABELS = {
    "article": "发布平台文章",
    "official_site": "修改官网页面",
    "structured_data": "补齐结构化数据",
    "third_party_source": "建设第三方信源",
    "legacy_unclassified": "优化行动",
}
UPLOAD_ROOT = Path(__file__).resolve().parents[2] / "private_artifacts" / "collaboration-uploads"
MAX_UPLOAD_BYTES = 150 * 1024 * 1024
MEDIA_LIMITS = {"image": 20 * 1024 * 1024, "video": MAX_UPLOAD_BYTES, "file": 50 * 1024 * 1024}
ALLOWED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
ALLOWED_VIDEO_MIME_TYPES = {"video/mp4", "video/webm", "video/quicktime"}
ALLOWED_FILE_MIME_TYPES = {
    "application/pdf",
    "application/zip",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/csv",
    "text/plain",
}
MODULE_SHARES = {
    "decision": ("决策洞察", "决策地图", "insights/decision"),
    "source": ("信源洞察", "信源地图", "sources"),
    "competitor": ("竞品洞察", "竞品对比", "competitors"),
    "question": ("问题洞察", "问题库", "questions"),
    "actions": ("优化行动", "优化行动工作台", "actions"),
    "content": ("内容", "内容中心", "content"),
    "results": ("效果与 ROI", "效果与 ROI", "results"),
    "operations": ("运营状态", "运营状态", "operations"),
    "alerts": ("变化告警", "变化告警", "alerts"),
    "settings": ("管理", "工作区管理", "settings"),
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class AttachmentRef(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    url: HttpUrl | None = None
    kind: Literal["link", "evidence", "file"] = "link"


class SharedObjectDraft(BaseModel):
    kind: Literal[
        "action", "alert", "question", "content_asset", "evidence", "module"
    ]
    object_id: int | None = Field(default=None, gt=0)
    module_key: str | None = Field(default=None, max_length=40)


class MessageCreate(BaseModel):
    context_type: Literal["action", "alert", "question", "evidence"]
    context_id: int = Field(gt=0)
    body: str = Field(default="", max_length=5000)
    mention_user_ids: list[int] = Field(default_factory=list, max_length=30)
    attachment_refs: list[AttachmentRef] = Field(default_factory=list, max_length=12)
    attachment_ids: list[int] = Field(default_factory=list, max_length=12)
    shared_objects: list[SharedObjectDraft] = Field(default_factory=list, max_length=6)
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")

    @model_validator(mode="after")
    def require_content(self):
        if not self.body.strip() and not self.attachment_refs and not self.attachment_ids and not self.shared_objects:
            raise ValueError("消息、附件或业务卡片至少填写一项")
        return self


class ChannelConfigure(BaseModel):
    provider: Literal["wecom", "feishu", "dingtalk"]
    connection_mode: Literal["webhook", "app"] = "webhook"
    webhook_url: HttpUrl | None = None
    corp_id: str | None = Field(default=None, max_length=255)
    app_id: str | None = Field(default=None, max_length=255)
    app_key: str | None = Field(default=None, max_length=255)
    agent_id: str | None = Field(default=None, max_length=80)
    app_secret: SecretStr | None = None
    display_name: str | None = Field(default=None, max_length=120)
    deep_link_base_url: HttpUrl | None = None


class MemberBindingUpdate(BaseModel):
    external_user_id: str = Field(min_length=1, max_length=255)
    external_id_type: Literal["user_id", "open_id", "union_id"] = "user_id"


class NotificationPreferenceUpdate(BaseModel):
    provider_settings: dict[Literal["wecom", "feishu", "dingtalk"], bool]
    event_types: list[
        Literal["assigned", "due_soon", "approval", "blocked", "progress", "manual_summary"]
    ] = Field(max_length=6)


class NotificationPreviewRequest(BaseModel):
    recipient_user_id: int = Field(gt=0)
    context_type: Literal["action", "alert", "question", "evidence"]
    context_id: int = Field(gt=0)
    event_type: Literal[
        "assigned", "due_soon", "approval", "blocked", "progress", "manual_summary"
    ] = "manual_summary"
    providers: list[Literal["wecom", "feishu", "dingtalk"]] = Field(
        default_factory=list, max_length=3
    )
    note: str = Field(default="", max_length=500)


class NotificationSendRequest(NotificationPreviewRequest):
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")


class WorkInfoUpdate(BaseModel):
    assignee_user_id: int | None = Field(default=None, gt=0)
    start_at: datetime | None = None
    due_at: datetime | None = None
    participant_user_ids: list[int] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.start_at and self.due_at and self.due_at < self.start_at:
            raise ValueError("截止日期不能早于开始日期")
        return self


def _context_or_404(db: Session, workspace_id: int, context_type: str, context_id: int):
    if context_type == "action":
        value = db.get(GeoOptimizationAction, context_id)
    elif context_type == "alert":
        value = db.get(GeoChangeAlert, context_id)
    elif context_type == "question":
        value = db.get(GeoQuestionPlan, context_id)
    elif context_type == "evidence":
        value = db.get(GeoEvidence, context_id)
    else:
        raise HTTPException(status_code=422, detail="不支持的会话对象")
    if value is None or value.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="会话对象不存在")
    return value


def _thread_work_info(
    thread: GeoCollaborationThread | None,
    *,
    assignee_user_id: int | None = None,
    start_at: datetime | None = None,
    due_at: datetime | None = None,
) -> dict:
    return {
        "assignee_user_id": thread.assignee_user_id if thread and thread.assignee_user_id else assignee_user_id,
        "start_at": thread.start_at if thread and thread.start_at else start_at,
        "due_at": thread.due_at if thread and thread.due_at else due_at,
        "participant_user_ids": list(thread.participant_user_ids or []) if thread else [],
    }


def _get_or_create_thread(
    db: Session,
    *,
    workspace_id: int,
    context_type: str,
    context_id: int,
    context,
    user_id: int,
) -> GeoCollaborationThread:
    thread = db.scalar(
        select(GeoCollaborationThread).where(
            GeoCollaborationThread.workspace_id == workspace_id,
            GeoCollaborationThread.context_type == context_type,
            GeoCollaborationThread.context_id == context_id,
        )
    )
    if thread is not None:
        return thread
    default_assignee = getattr(context, "assignee_user_id", None)
    default_start = (
        getattr(context, "selected_at", None)
        or getattr(context, "captured_at", None)
        or getattr(context, "created_at", None)
        or utcnow()
    )
    default_due = getattr(context, "due_at", None)
    participant_ids = sorted({value for value in (user_id, default_assignee) if value})
    thread = GeoCollaborationThread(
        workspace_id=workspace_id,
        context_type=context_type,
        context_id=context_id,
        status="active",
        created_by_user_id=user_id,
        assignee_user_id=default_assignee,
        start_at=default_start,
        due_at=default_due,
        participant_user_ids=participant_ids,
    )
    db.add(thread)
    db.flush()
    return thread


def _members(db: Session, workspace_id: int, current_user: User) -> list[dict]:
    rows = db.execute(
        select(WorkspaceMembership, User)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.status == "active",
            User.status == "active",
        )
        .order_by(WorkspaceMembership.role.asc(), User.name.asc(), User.id.asc())
    ).all()
    members = [
        {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": membership.role,
            "initial": (user.name or user.email or "U").strip()[:1].upper(),
        }
        for membership, user in rows
    ]
    if all(item["id"] != current_user.id for item in members):
        members.insert(
            0,
            {
                "id": current_user.id,
                "name": current_user.name,
                "email": current_user.email,
                "role": "admin" if current_user.role == "super_admin" else "operator",
                "initial": (current_user.name or current_user.email or "U").strip()[:1].upper(),
            },
        )
    bindings_by_user: dict[int, list[dict]] = {}
    for binding in db.scalars(
        select(GeoCollaborationMemberBinding).where(
            GeoCollaborationMemberBinding.workspace_id == workspace_id
        )
    ):
        bindings_by_user.setdefault(binding.user_id, []).append(
            {
                "provider": binding.provider,
                "status": binding.status,
                "external_id_type": binding.external_id_type,
                "external_display_name": binding.external_display_name,
                "verified_at": binding.verified_at,
            }
        )
    preferences = {
        row.user_id: row
        for row in db.scalars(
            select(GeoCollaborationNotificationPreference).where(
                GeoCollaborationNotificationPreference.workspace_id == workspace_id
            )
        )
    }
    deliveries_by_user: dict[int, list[dict]] = {}
    delivery_rows = list(
        db.scalars(
            select(GeoCollaborationDelivery)
            .where(GeoCollaborationDelivery.workspace_id == workspace_id)
            .order_by(GeoCollaborationDelivery.id.desc())
            .limit(100)
        )
    )
    for delivery in delivery_rows:
        values = deliveries_by_user.setdefault(delivery.recipient_user_id, [])
        if len(values) < 8:
            values.append(_delivery_payload(delivery))
    default_events = ["assigned", "due_soon", "approval", "blocked", "progress", "manual_summary"]
    for member in members:
        preference = preferences.get(member["id"])
        member["bindings"] = bindings_by_user.get(member["id"], [])
        member["notification_preferences"] = {
            "provider_settings": dict(preference.provider_settings or {}) if preference else {},
            "event_types": list(preference.event_types or []) if preference else default_events,
        }
        member["recent_deliveries"] = deliveries_by_user.get(member["id"], [])
    return members


def _delivery_payload(row: GeoCollaborationDelivery) -> dict:
    return {
        "id": row.id,
        "provider": row.provider,
        "connection_mode": row.connection_mode,
        "context_type": row.context_type,
        "context_id": row.context_id,
        "event_type": row.event_type,
        "status": row.status,
        "provider_message_ref": row.provider_message_ref,
        "error_code": row.error_code,
        "attempted_at": row.attempted_at,
        "accepted_at": row.accepted_at,
    }


def _action_progress(db: Session, action: GeoOptimizationAction) -> tuple[int, int, int]:
    targets = list(
        db.scalars(
            select(GeoActionTarget)
            .where(GeoActionTarget.action_id == action.id)
            .order_by(GeoActionTarget.ordinal.asc(), GeoActionTarget.id.asc())
        )
    )
    if not targets:
        stage_percent = {
            "proposed": 0,
            "accepted": 10,
            "in_progress": 30,
            "awaiting_approval": 55,
            "executing": 70,
            "partially_completed": 80,
            "completed": 100,
            "blocked": 30,
            "changes_requested": 35,
            "cancelled": 0,
        }
        return stage_percent.get(action.stage, 0), 0, 0
    completed = 0
    total_steps = 0
    completed_steps = 0
    for target in targets:
        workflow = TARGET_WORKFLOWS.get(action.action_type, (target.delivery_status,))
        total_steps += max(1, len(workflow) - 1)
        try:
            completed_steps += min(workflow.index(target.delivery_status), len(workflow) - 1)
        except ValueError:
            completed_steps += 0
        if target.delivery_status == workflow[-1]:
            completed += 1
    percent = round(completed_steps / total_steps * 100) if total_steps else 0
    return percent, completed, len(targets)


def _thread_map(db: Session, workspace_id: int) -> dict[tuple[str, int], GeoCollaborationThread]:
    return {
        (row.context_type, row.context_id): row
        for row in db.scalars(
            select(GeoCollaborationThread).where(
                GeoCollaborationThread.workspace_id == workspace_id,
                GeoCollaborationThread.status == "active",
            )
        )
    }


def _thread_stats(
    db: Session,
    threads: dict[tuple[str, int], GeoCollaborationThread],
    current_user_id: int,
    user_names: dict[int, str],
) -> dict[int, dict]:
    """Build exact summaries with bounded SQL aggregates, never all-row materialization."""
    thread_ids = [thread.id for thread in threads.values()]
    if not thread_ids:
        return {}
    stats = {
        thread_id: {
            "message_count": 0,
            "unread_count": 0,
            "last_message_preview": None,
            "last_message_author_name": None,
            "mentioned_current_user": False,
        }
        for thread_id in thread_ids
    }
    latest_ids = (
        select(
            GeoCollaborationMessage.thread_id.label("thread_id"),
            func.max(GeoCollaborationMessage.id).label("message_id"),
        )
        .where(GeoCollaborationMessage.thread_id.in_(thread_ids))
        .group_by(GeoCollaborationMessage.thread_id)
        .subquery()
    )
    for thread_id, count in db.execute(
        select(
            GeoCollaborationMessage.thread_id,
            func.count(GeoCollaborationMessage.id),
        )
        .where(GeoCollaborationMessage.thread_id.in_(thread_ids))
        .group_by(GeoCollaborationMessage.thread_id)
    ):
        stats[int(thread_id)]["message_count"] = int(count or 0)
    latest_messages = db.scalars(
        select(GeoCollaborationMessage).join(
            latest_ids,
            and_(
                latest_ids.c.thread_id == GeoCollaborationMessage.thread_id,
                latest_ids.c.message_id == GeoCollaborationMessage.id,
            ),
        )
    )
    for message in latest_messages:
        summary = stats[message.thread_id]
        summary["last_message_preview"] = (
            message.body.strip()
            or ("[附件]" if message.attachment_refs else "[消息]")
        )[:120]
        summary["last_message_author_name"] = user_names.get(
            message.author_user_id or 0, "系统"
        )
    for thread_id, count in db.execute(
        select(
            GeoCollaborationMessage.thread_id,
            func.count(GeoCollaborationMessage.id),
        )
        .outerjoin(
            GeoCollaborationRead,
            and_(
                GeoCollaborationRead.thread_id == GeoCollaborationMessage.thread_id,
                GeoCollaborationRead.user_id == current_user_id,
            ),
        )
        .where(
            GeoCollaborationMessage.thread_id.in_(thread_ids),
            or_(
                GeoCollaborationMessage.author_user_id.is_(None),
                GeoCollaborationMessage.author_user_id != current_user_id,
            ),
            or_(
                GeoCollaborationRead.id.is_(None),
                GeoCollaborationRead.last_read_message_id.is_(None),
                GeoCollaborationMessage.id > GeoCollaborationRead.last_read_message_id,
            ),
        )
        .group_by(GeoCollaborationMessage.thread_id)
    ):
        stats[int(thread_id)]["unread_count"] = int(count or 0)
    mentioned_threads = set(
        db.scalars(
            select(GeoCollaborationMention.thread_id)
            .where(
                GeoCollaborationMention.thread_id.in_(thread_ids),
                GeoCollaborationMention.user_id == current_user_id,
            )
            .distinct()
        )
    )
    for thread_id in mentioned_threads:
        stats[int(thread_id)]["mentioned_current_user"] = True
    return stats


def _action_item(
    db: Session,
    action: GeoOptimizationAction,
    thread: GeoCollaborationThread | None,
    thread_stat: dict | None,
    current_user_id: int,
    user_names: dict[int, str],
) -> dict:
    progress, completed_targets, target_count = _action_progress(db, action)
    pending_approvals = int(
        db.scalar(
            select(func.count(GeoActionApproval.id)).where(
                GeoActionApproval.action_id == action.id,
                GeoActionApproval.status == "pending",
            )
        )
        or 0
    )
    evidence_count = int(
        db.scalar(
            select(func.count(GeoActionCompletionEvidence.id)).where(
                GeoActionCompletionEvidence.action_id == action.id,
                GeoActionCompletionEvidence.verification_status == "verified",
            )
        )
        or 0
    )
    thread_stat = thread_stat or {}
    due_soon = bool(
        action.due_at
        and as_utc(action.due_at) <= utcnow() + timedelta(days=7)
        and action.stage not in {"completed", "cancelled"}
    )
    attention_reason = None
    if thread_stat.get("mentioned_current_user") and thread_stat.get("unread_count"):
        attention_reason = "有人提醒了你"
    elif pending_approvals:
        attention_reason = "有待处理的审批"
    elif action.stage == "blocked":
        attention_reason = "行动正在阻塞"
    elif action.assignee_user_id == current_user_id and due_soon:
        attention_reason = "7 天内到期"
    elif thread_stat.get("unread_count"):
        attention_reason = "有新消息"
    work_info = _thread_work_info(
        thread,
        assignee_user_id=action.assignee_user_id,
        start_at=action.selected_at or action.created_at,
        due_at=action.due_at,
    )
    return {
        "key": f"action:{action.id}",
        "context_type": "action",
        "context_id": action.id,
        "thread_id": thread.id if thread else None,
        "title": action.title,
        "category": ACTION_TYPE_LABELS.get(action.action_type, "优化行动"),
        "status": action.stage,
        "priority": action.priority,
        **work_info,
        "assignee_name": user_names.get(work_info["assignee_user_id"] or 0),
        "progress": progress,
        "target_progress": {"completed": completed_targets, "total": target_count},
        "pending_approvals": pending_approvals,
        "evidence_count": evidence_count,
        "question_ids": list(action.affected_question_ids or []),
        "model_keys": list(action.affected_model_keys or []),
        "blocked_note": action.blocked_note or action.blocked_reason,
        "message_count": int(thread_stat.get("message_count") or 0),
        "has_conversation": bool(thread_stat.get("message_count")),
        "last_message_preview": thread_stat.get("last_message_preview"),
        "last_message_author_name": thread_stat.get("last_message_author_name"),
        "mentioned_current_user": bool(thread_stat.get("mentioned_current_user")),
        "requires_attention": attention_reason is not None,
        "attention_reason": attention_reason,
        "unread_count": int(thread_stat.get("unread_count") or 0),
        "last_activity_at": thread.last_message_at if thread and thread.last_message_at else action.updated_at,
    }


def _alert_item(
    db: Session,
    alert: GeoChangeAlert,
    thread: GeoCollaborationThread | None,
    thread_stat: dict | None,
) -> dict:
    thread_stat = thread_stat or {}
    attention_reason = None
    if thread_stat.get("mentioned_current_user") and thread_stat.get("unread_count"):
        attention_reason = "有人提醒了你"
    elif alert.status == "open":
        attention_reason = "告警待处理"
    elif thread_stat.get("unread_count"):
        attention_reason = "有新消息"
    work_info = _thread_work_info(thread, start_at=alert.created_at)
    return {
        "key": f"alert:{alert.id}",
        "context_type": "alert",
        "context_id": alert.id,
        "thread_id": thread.id if thread else None,
        "title": alert.title,
        "category": "变化告警",
        "status": alert.status,
        "priority": alert.severity,
        **work_info,
        "assignee_name": None,
        "progress": 0 if alert.status == "open" else 100,
        "target_progress": {"completed": 0, "total": 0},
        "pending_approvals": 0,
        "evidence_count": len(alert.evidence_ids or []),
        "question_ids": list((alert.scope_snapshot or {}).get("question_plan_ids") or []),
        "model_keys": list((alert.scope_snapshot or {}).get("model_keys") or []),
        "blocked_note": alert.summary,
        "message_count": int(thread_stat.get("message_count") or 0),
        "has_conversation": bool(thread_stat.get("message_count")),
        "last_message_preview": thread_stat.get("last_message_preview"),
        "last_message_author_name": thread_stat.get("last_message_author_name"),
        "mentioned_current_user": bool(thread_stat.get("mentioned_current_user")),
        "requires_attention": attention_reason is not None,
        "attention_reason": attention_reason,
        "unread_count": int(thread_stat.get("unread_count") or 0),
        "last_activity_at": thread.last_message_at if thread and thread.last_message_at else alert.updated_at,
    }


def _question_item(
    question: GeoQuestionPlan,
    thread: GeoCollaborationThread | None,
    thread_stat: dict | None,
    user_names: dict[int, str],
) -> dict:
    """Represent one real question as a discussable collaboration context."""
    thread_stat = thread_stat or {}
    attention_reason = None
    if thread_stat.get("mentioned_current_user") and thread_stat.get("unread_count"):
        attention_reason = "有人提醒了你"
    elif thread_stat.get("unread_count"):
        attention_reason = "有新消息"
    priority = "high" if question.importance >= 4 else "medium" if question.importance >= 2 else "low"
    work_info = _thread_work_info(thread, start_at=question.created_at)
    return {
        "key": f"question:{question.id}",
        "context_type": "question",
        "context_id": question.id,
        "thread_id": thread.id if thread else None,
        "title": question.question_text,
        "category": "问题讨论",
        "status": question.status,
        "priority": priority,
        **work_info,
        "assignee_name": user_names.get(work_info["assignee_user_id"] or 0),
        "progress": 0,
        "target_progress": {"completed": 0, "total": 0},
        "pending_approvals": 0,
        "evidence_count": 0,
        "question_ids": [question.id],
        "model_keys": [],
        "blocked_note": question.source_reason,
        "message_count": int(thread_stat.get("message_count") or 0),
        "has_conversation": bool(thread_stat.get("message_count")),
        "last_message_preview": thread_stat.get("last_message_preview"),
        "last_message_author_name": thread_stat.get("last_message_author_name"),
        "mentioned_current_user": bool(thread_stat.get("mentioned_current_user")),
        "requires_attention": attention_reason is not None,
        "attention_reason": attention_reason,
        "unread_count": int(thread_stat.get("unread_count") or 0),
        "last_activity_at": thread.last_message_at if thread and thread.last_message_at else question.updated_at,
    }


def _evidence_item(
    evidence: GeoEvidence,
    question: GeoQuestionPlan | None,
    thread: GeoCollaborationThread | None,
    thread_stat: dict | None,
    user_names: dict[int, str],
) -> dict:
    """Expose one immutable observed answer as a discussable insight result."""
    thread_stat = thread_stat or {}
    work_info = _thread_work_info(thread, start_at=evidence.captured_at)
    title = question.question_text if question else f"观测结果 #{evidence.id}"
    attention_reason = None
    if thread_stat.get("mentioned_current_user") and thread_stat.get("unread_count"):
        attention_reason = "有人提醒了你"
    elif thread_stat.get("unread_count"):
        attention_reason = "有新消息"
    sources = list(evidence.source_items or [])
    return {
        "key": f"evidence:{evidence.id}",
        "context_type": "evidence",
        "context_id": evidence.id,
        "thread_id": thread.id if thread else None,
        "title": title,
        "category": f"观测洞察 · {evidence.model_label}",
        "status": evidence.brand_status,
        "priority": "high" if evidence.brand_status == "absent" else "medium",
        **work_info,
        "assignee_name": user_names.get(work_info["assignee_user_id"] or 0),
        "progress": 100,
        "target_progress": {"completed": 1, "total": 1},
        "pending_approvals": 0,
        "evidence_count": len(sources),
        "question_ids": [evidence.question_plan_id],
        "model_keys": [evidence.model_key],
        "blocked_note": None,
        "message_count": int(thread_stat.get("message_count") or 0),
        "has_conversation": bool(thread_stat.get("message_count")),
        "last_message_preview": thread_stat.get("last_message_preview"),
        "last_message_author_name": thread_stat.get("last_message_author_name"),
        "mentioned_current_user": bool(thread_stat.get("mentioned_current_user")),
        "requires_attention": attention_reason is not None,
        "attention_reason": attention_reason,
        "unread_count": int(thread_stat.get("unread_count") or 0),
        "last_activity_at": thread.last_message_at if thread and thread.last_message_at else evidence.captured_at,
    }


def _message_payload(row: GeoCollaborationMessage, users: dict[int, dict]) -> dict:
    return {
        "id": row.id,
        "kind": row.message_type,
        "body": row.body,
        "author": users.get(row.author_user_id or 0),
        "mention_user_ids": list(row.mention_user_ids or []),
        "attachment_refs": list(row.attachment_refs or []),
        "created_at": row.created_at,
    }


def _messages(db: Session, thread: GeoCollaborationThread | None, users: dict[int, dict]) -> list[dict]:
    if thread is None:
        return []
    rows = list(
        db.scalars(
            select(GeoCollaborationMessage)
            .where(GeoCollaborationMessage.thread_id == thread.id)
            .order_by(GeoCollaborationMessage.id.asc())
            .limit(200)
        )
    )
    return [_message_payload(row, users) for row in rows]


def _action_activity(db: Session, action_id: int, users: dict[int, dict]) -> list[dict]:
    rows = list(
        db.scalars(
            select(GeoActionEvent)
            .where(GeoActionEvent.action_id == action_id)
            .order_by(GeoActionEvent.id.desc())
            .limit(12)
        )
    )
    return [
        {
            "id": f"event:{row.id}",
            "kind": "system",
            "event_type": row.event_type,
            "from_stage": row.from_stage,
            "to_stage": row.to_stage,
            "detail": row.detail or {},
            "author": users.get(row.actor_user_id or 0),
            "created_at": row.created_at,
        }
        for row in reversed(rows)
    ]


def _channels(db: Session, workspace_id: int) -> list[dict]:
    configured = {
        row.provider: row
        for row in db.scalars(
            select(GeoCollaborationChannel).where(
                GeoCollaborationChannel.workspace_id == workspace_id
            )
        )
    }
    return [
        {
            "provider": provider,
            "label": CHANNEL_LABELS[provider],
            "status": configured[provider].status if provider in configured else "disconnected",
            "display_name": configured[provider].display_name if provider in configured else None,
            "connection_mode": configured[provider].connection_mode if provider in configured else None,
            "configured_fields": list(configured[provider].configured_fields or []) if provider in configured else [],
            "capabilities": dict(configured[provider].capabilities or {}) if provider in configured else {},
            "deep_link_base_url": configured[provider].deep_link_base_url if provider in configured else None,
            "configured_at": configured[provider].configured_at if provider in configured else None,
            "last_tested_at": configured[provider].last_tested_at if provider in configured else None,
            "last_error_code": configured[provider].last_error_code if provider in configured else None,
        }
        for provider in ("wecom", "feishu", "dingtalk")
    ]


def _credential_key(provider: str, mode: str, field: str) -> str:
    if mode == "webhook" and field == "webhook_url":
        return f"collaboration_{provider}_webhook_url"
    return f"collaboration_{provider}_{mode}_{field}"


def _channel_credentials(
    db: Session, workspace_id: int, provider: str, mode: str
) -> dict[str, str]:
    return {
        field: value
        for field in required_fields(provider, mode)
        if (
            value := get_workspace_secret(
                db, workspace_id, _credential_key(provider, mode, field)
            )
        )
    }


def _office_http_error(exc: OfficeProviderError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.user_message)


def _media_kind(mime_type: str) -> str:
    normalized = mime_type.split(";", 1)[0].strip().lower()
    if normalized in ALLOWED_IMAGE_MIME_TYPES:
        return "image"
    if normalized in ALLOWED_VIDEO_MIME_TYPES:
        return "video"
    if normalized in ALLOWED_FILE_MIME_TYPES:
        return "file"
    raise HTTPException(status_code=415, detail="不支持这种文件格式")


def _valid_media_signature(mime_type: str, header: bytes) -> bool:
    if mime_type == "image/png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/jpeg":
        return header.startswith(b"\xff\xd8\xff")
    if mime_type == "image/gif":
        return header.startswith((b"GIF87a", b"GIF89a"))
    if mime_type == "image/webp":
        return header.startswith(b"RIFF") and header[8:12] == b"WEBP"
    if mime_type in {"video/mp4", "video/quicktime"}:
        return len(header) >= 12 and header[4:8] == b"ftyp"
    if mime_type == "video/webm":
        return header.startswith(b"\x1a\x45\xdf\xa3")
    return True


def _attachment_payload(row: GeoCollaborationAttachment) -> dict:
    return {
        "kind": row.media_kind,
        "attachment_id": row.id,
        "label": row.original_name,
        "mime_type": row.mime_type,
        "byte_size": row.byte_size,
        "url": f"/api/geo/{row.workspace_id}/collaboration/attachments/{row.id}",
    }


def _shared_object_payload(
    db: Session, workspace_id: int, draft: SharedObjectDraft
) -> dict:
    if draft.kind == "module":
        value = MODULE_SHARES.get(draft.module_key or "")
        if value is None:
            raise HTTPException(status_code=422, detail="不支持的 GEO 页面")
        module_label, title, route = value
        return {
            "kind": "geo_object",
            "object_type": "module",
            "object_key": draft.module_key,
            "module_label": module_label,
            "title": title,
            "subtitle": "来自当前工作区",
            "href": f"/geo/{workspace_id}/{route}",
        }
    if not draft.object_id:
        raise HTTPException(status_code=422, detail="业务对象缺少编号")
    if draft.kind == "action":
        row = db.get(GeoOptimizationAction, draft.object_id)
        payload = ("优化行动", row.title if row else "", row.stage if row else "", f"actions?action_id={draft.object_id}")
    elif draft.kind == "alert":
        row = db.get(GeoChangeAlert, draft.object_id)
        payload = ("变化告警", row.title if row else "", row.status if row else "", "alerts")
    elif draft.kind == "question":
        row = db.get(GeoQuestionPlan, draft.object_id)
        payload = ("问题洞察", row.question_text if row else "", row.status if row else "", f"questions?question={draft.object_id}")
    elif draft.kind == "content_asset":
        row = db.get(GeoContentAsset, draft.object_id)
        payload = ("内容资产", row.title if row else "", row.status if row else "", f"content?asset={draft.object_id}")
    else:
        row = db.get(GeoEvidence, draft.object_id)
        payload = ("观测证据", f"证据 #{draft.object_id}", row.brand_status if row else "", f"evidence/{draft.object_id}")
    if row is None or row.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="要分享的业务对象不存在")
    module_label, title, status, route = payload
    return {
        "kind": "geo_object",
        "object_type": draft.kind,
        "object_id": draft.object_id,
        "module_label": module_label,
        "title": title,
        "subtitle": status,
        "href": f"/geo/{workspace_id}/{route}",
    }


def _safe_upload_path(row: GeoCollaborationAttachment) -> Path:
    root = UPLOAD_ROOT.resolve()
    path = (root / row.storage_key).resolve()
    if root not in path.parents:
        raise HTTPException(status_code=404, detail="附件不存在")
    return path


def _attachment_usage(db: Session, *, workspace_id: int, user_id: int) -> tuple[int, int, int]:
    active = GeoCollaborationAttachment.status != "deleted"
    workspace_bytes, workspace_count = db.execute(
        select(
            func.coalesce(func.sum(GeoCollaborationAttachment.byte_size), 0),
            func.count(GeoCollaborationAttachment.id),
        ).where(GeoCollaborationAttachment.workspace_id == workspace_id, active)
    ).one()
    user_bytes = db.scalar(
        select(func.coalesce(func.sum(GeoCollaborationAttachment.byte_size), 0)).where(
            GeoCollaborationAttachment.workspace_id == workspace_id,
            GeoCollaborationAttachment.uploader_user_id == user_id,
            active,
        )
    )
    return int(workspace_bytes or 0), int(user_bytes or 0), int(workspace_count or 0)


def _enforce_attachment_capacity(
    db: Session,
    *,
    workspace_id: int,
    user_id: int,
    reserved_bytes: int,
) -> None:
    settings = get_settings()
    workspace_bytes, user_bytes, workspace_count = _attachment_usage(
        db,
        workspace_id=workspace_id,
        user_id=user_id,
    )
    if workspace_count >= settings.collaboration_attachment_count_quota:
        raise HTTPException(status_code=413, detail="工作区附件数量已达到上限")
    if workspace_bytes + reserved_bytes > settings.collaboration_workspace_storage_quota_bytes:
        raise HTTPException(status_code=413, detail="工作区附件存储空间不足")
    if user_bytes + reserved_bytes > settings.collaboration_user_storage_quota_bytes:
        raise HTTPException(status_code=413, detail="你的附件存储空间已达到上限")
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    free_bytes = shutil.disk_usage(UPLOAD_ROOT).free
    safety_reserve = max(256 * 1024 * 1024, reserved_bytes * 2)
    if free_bytes - reserved_bytes < safety_reserve:
        raise HTTPException(status_code=507, detail="服务器可用存储空间不足")


@router.post("/workspaces/{workspace_id}/collaboration/attachments", status_code=201)
async def upload_collaboration_attachment(
    workspace_id: int,
    request: Request,
    x_file_name: str = Header(..., max_length=900),
    x_file_size: int | None = Header(default=None, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_workspace_access(db, user, workspace_id)
    mime_type = request.headers.get("content-type", "application/octet-stream").split(";", 1)[0].lower()
    kind = _media_kind(mime_type)
    limit = MEDIA_LIMITS[kind]
    if x_file_size is not None and x_file_size > limit:
        raise HTTPException(status_code=413, detail="文件超过允许大小")
    if x_file_size == 0:
        raise HTTPException(status_code=422, detail="不能上传空文件")
    settings = get_settings()
    retry_after = consume_security_rate_limit(
        db,
        scope="collaboration-upload",
        identity=f"{workspace_id}:{user.id}",
        limit=settings.collaboration_upload_rate_limit_per_10_minutes,
        window=timedelta(minutes=10),
    )
    db.commit()
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="附件上传过于频繁，请稍后重试",
            headers={"Retry-After": str(retry_after)},
        )
    db.scalar(
        select(GeoWorkspace).where(GeoWorkspace.id == workspace_id).with_for_update()
    )
    _enforce_attachment_capacity(
        db,
        workspace_id=workspace_id,
        user_id=user.id,
        reserved_bytes=x_file_size if x_file_size is not None else limit,
    )
    original_name = Path(unquote(x_file_name)).name.strip()[:255]
    if not original_name:
        raise HTTPException(status_code=422, detail="文件名不能为空")
    suffix = re.sub(r"[^A-Za-z0-9.]", "", Path(original_name).suffix.lower())[:12]
    storage_key = f"{workspace_id}/{uuid4().hex}{suffix}"
    target = (UPLOAD_ROOT / storage_key).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = sha256()
    total = 0
    header = bytearray()
    try:
        with target.open("xb") as stream:
            async for chunk in request.stream():
                total += len(chunk)
                if total > limit:
                    raise HTTPException(status_code=413, detail="文件超过允许大小")
                if len(header) < 16:
                    header.extend(chunk[: 16 - len(header)])
                digest.update(chunk)
                stream.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    if total == 0:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="不能上传空文件")
    if x_file_size is not None and total != x_file_size:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="文件大小与声明不一致")
    if kind in {"image", "video"} and not _valid_media_signature(mime_type, bytes(header)):
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=415, detail="文件内容与格式不一致")
    row = GeoCollaborationAttachment(
        workspace_id=workspace_id,
        uploader_user_id=user.id,
        original_name=original_name,
        storage_key=storage_key,
        mime_type=mime_type,
        byte_size=total,
        sha256=digest.hexdigest(),
        media_kind=kind,
        status="available",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _attachment_payload(row)


@router.get("/workspaces/{workspace_id}/collaboration/attachments/{attachment_id}")
def read_collaboration_attachment(
    workspace_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_workspace_access(db, user, workspace_id)
    row = db.get(GeoCollaborationAttachment, attachment_id)
    if row is None or row.workspace_id != workspace_id or row.status == "deleted":
        raise HTTPException(status_code=404, detail="附件不存在")
    path = _safe_upload_path(row)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="附件文件不存在")
    return FileResponse(
        path,
        media_type=row.mime_type,
        filename=row.original_name,
        content_disposition_type="inline" if row.media_kind in {"image", "video"} else "attachment",
    )


@router.delete("/workspaces/{workspace_id}/collaboration/attachments/{attachment_id}", status_code=204)
def delete_collaboration_attachment(
    workspace_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_workspace_access(db, user, workspace_id)
    row = db.get(GeoCollaborationAttachment, attachment_id)
    if row is None or row.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="附件不存在")
    if row.uploader_user_id != user.id or row.message_id is not None:
        raise HTTPException(status_code=409, detail="已发送的附件不能从消息中删除")
    _safe_upload_path(row).unlink(missing_ok=True)
    row.status = "deleted"
    db.commit()


@router.get("/workspaces/{workspace_id}/collaboration")
def get_collaboration_center(
    workspace_id: int,
    context_type: str | None = Query(default=None),
    context_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_workspace_access(db, user, workspace_id)
    members = _members(db, workspace_id, user)
    users = {item["id"]: item for item in members}
    user_names = {item["id"]: item["name"] for item in members}
    threads = _thread_map(db, workspace_id)
    thread_stats = _thread_stats(db, threads, user.id, user_names)
    actions = list(
        db.scalars(
            select(GeoOptimizationAction)
            .where(GeoOptimizationAction.workspace_id == workspace_id)
            .order_by(GeoOptimizationAction.updated_at.desc(), GeoOptimizationAction.id.desc())
            .limit(100)
        )
    )
    alerts = list(
        db.scalars(
            select(GeoChangeAlert)
            .where(GeoChangeAlert.workspace_id == workspace_id)
            .order_by(GeoChangeAlert.updated_at.desc(), GeoChangeAlert.id.desc())
            .limit(50)
        )
    )
    questions = list(
        db.scalars(
            select(GeoQuestionPlan)
            .where(
                GeoQuestionPlan.workspace_id == workspace_id,
                GeoQuestionPlan.active.is_(True),
            )
            .order_by(GeoQuestionPlan.updated_at.desc(), GeoQuestionPlan.id.desc())
            .limit(200)
        )
    )
    evidences = list(
        db.scalars(
            select(GeoEvidence)
            .where(GeoEvidence.workspace_id == workspace_id)
            .order_by(GeoEvidence.captured_at.desc(), GeoEvidence.id.desc())
            .limit(100)
        )
    )
    questions_by_id = {question.id: question for question in questions}
    items = [
        _action_item(
            db,
            action,
            threads.get(("action", action.id)),
            thread_stats.get(threads[("action", action.id)].id)
            if ("action", action.id) in threads
            else None,
            user.id,
            user_names,
        )
        for action in actions
    ] + [
        _alert_item(
            db,
            alert,
            threads.get(("alert", alert.id)),
            thread_stats.get(threads[("alert", alert.id)].id)
            if ("alert", alert.id) in threads
            else None,
        )
        for alert in alerts
    ] + [
        _question_item(
            question,
            threads.get(("question", question.id)),
            thread_stats.get(threads[("question", question.id)].id)
            if ("question", question.id) in threads
            else None,
            user_names,
        )
        for question in questions
    ] + [
        _evidence_item(
            evidence,
            questions_by_id.get(evidence.question_plan_id),
            threads.get(("evidence", evidence.id)),
            thread_stats.get(threads[("evidence", evidence.id)].id)
            if ("evidence", evidence.id) in threads
            else None,
            user_names,
        )
        for evidence in evidences
    ]
    items.sort(key=lambda item: (item["last_activity_at"], item["context_id"]), reverse=True)
    requested = next(
        (
            item
            for item in items
            if item["context_type"] == context_type and item["context_id"] == context_id
        ),
        None,
    )
    selected = requested or next(
        (item for item in items if item["has_conversation"]),
        items[0] if items else None,
    )
    selected_thread = (
        threads.get((selected["context_type"], selected["context_id"])) if selected else None
    )
    selected_context = None
    if selected:
        selected_context = _context_or_404(
            db, workspace_id, selected["context_type"], selected["context_id"]
        )
    question_ids = list(selected.get("question_ids") or []) if selected else []
    question_rows = list(
        db.scalars(
            select(GeoQuestionPlan).where(
                GeoQuestionPlan.workspace_id == workspace_id,
                GeoQuestionPlan.id.in_(question_ids),
            )
        )
    ) if question_ids else []
    unread_total = sum(int(item["unread_count"]) for item in items)
    mentions = int(
        db.scalar(
            select(func.count(GeoCollaborationMessage.id)).where(
                GeoCollaborationMessage.workspace_id == workspace_id,
                GeoCollaborationMessage.author_user_id != user.id,
                GeoCollaborationMessage.mention_user_ids.contains([user.id]),
            )
        )
        or 0
    )
    return {
        "workspace_id": workspace_id,
        "current_user_id": user.id,
        "members": members,
        "summary": {
            "unread": unread_total,
            "mentions": mentions,
            "pending_approvals": sum(int(item["pending_approvals"]) for item in items),
            "blocked": sum(1 for item in items if item["status"] == "blocked"),
        },
        "items": items,
        "selected": selected,
        "selected_detail": {
            "rationale": getattr(selected_context, "rationale", None),
            "summary": getattr(selected_context, "summary", None)
            or getattr(selected_context, "answer_text", None),
            "questions": [{"id": row.id, "text": row.question_text} for row in question_rows],
            "messages": _messages(db, selected_thread, users),
            "activity": _action_activity(db, selected["context_id"], users)
            if selected and selected["context_type"] == "action"
            else [],
        } if selected else None,
        "channels": _channels(db, workspace_id),
    }


@router.post("/workspaces/{workspace_id}/collaboration/messages", status_code=201)
def create_collaboration_message(
    workspace_id: int,
    payload: MessageCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_workspace_access(db, user, workspace_id)
    context = _context_or_404(db, workspace_id, payload.context_type, payload.context_id)
    members = _members(db, workspace_id, user)
    users = {item["id"]: item for item in members}
    duplicate = db.scalar(
        select(GeoCollaborationMessage).where(
            GeoCollaborationMessage.workspace_id == workspace_id,
            GeoCollaborationMessage.idempotency_key == payload.idempotency_key,
        )
    )
    if duplicate:
        return {
            "id": duplicate.id,
            "thread_id": duplicate.thread_id,
            "created_at": duplicate.created_at,
            "message": _message_payload(duplicate, users),
        }
    settings = get_settings()
    retry_after = consume_security_rate_limit(
        db,
        scope="collaboration-message",
        identity=f"{workspace_id}:{user.id}",
        limit=settings.collaboration_message_rate_limit_per_10_minutes,
        window=timedelta(minutes=10),
    )
    db.commit()
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="消息发送过于频繁，请稍后重试",
            headers={"Retry-After": str(retry_after)},
        )
    db.scalar(
        select(GeoWorkspace).where(GeoWorkspace.id == workspace_id).with_for_update()
    )
    message_count = int(
        db.scalar(
            select(func.count(GeoCollaborationMessage.id)).where(
                GeoCollaborationMessage.workspace_id == workspace_id
            )
        )
        or 0
    )
    if message_count >= settings.collaboration_message_count_quota:
        raise HTTPException(status_code=413, detail="工作区消息数量已达到上限，请先归档历史讨论")
    active_member_ids = set(
        db.scalars(
            select(WorkspaceMembership.user_id).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.status == "active",
            )
        )
    )
    active_member_ids.add(user.id)
    mention_ids = sorted(set(payload.mention_user_ids))
    if any(value not in active_member_ids for value in mention_ids):
        raise HTTPException(status_code=422, detail="@的成员不在当前工作区")
    attachment_ids = sorted(set(payload.attachment_ids))
    uploaded = list(
        db.scalars(
            select(GeoCollaborationAttachment).where(
                GeoCollaborationAttachment.id.in_(attachment_ids)
            )
        )
    ) if attachment_ids else []
    if len(uploaded) != len(attachment_ids) or any(
        row.workspace_id != workspace_id
        or row.uploader_user_id != user.id
        or row.status != "available"
        or row.message_id is not None
        for row in uploaded
    ):
        raise HTTPException(status_code=422, detail="附件无效、已发送或不属于当前工作区")
    canonical_refs = [item.model_dump(mode="json") for item in payload.attachment_refs]
    canonical_refs.extend(_attachment_payload(row) for row in uploaded)
    canonical_refs.extend(
        _shared_object_payload(db, workspace_id, item) for item in payload.shared_objects
    )
    thread = _get_or_create_thread(
        db,
        workspace_id=workspace_id,
        context_type=payload.context_type,
        context_id=payload.context_id,
        context=context,
        user_id=user.id,
    )
    message = GeoCollaborationMessage(
        workspace_id=workspace_id,
        thread_id=thread.id,
        author_user_id=user.id,
        message_type="comment",
        body=payload.body.strip(),
        mention_user_ids=mention_ids,
        attachment_refs=canonical_refs,
        idempotency_key=payload.idempotency_key,
    )
    db.add(message)
    db.flush()
    for mentioned_user_id in mention_ids:
        db.add(
            GeoCollaborationMention(
                workspace_id=workspace_id,
                thread_id=thread.id,
                message_id=message.id,
                user_id=mentioned_user_id,
            )
        )
    for attachment in uploaded:
        attachment.message_id = message.id
        attachment.status = "attached"
    thread.last_message_at = message.created_at or utcnow()
    thread.participant_user_ids = sorted(
        set(thread.participant_user_ids or []) | {user.id} | set(mention_ids)
    )
    read = db.scalar(
        select(GeoCollaborationRead).where(
            GeoCollaborationRead.thread_id == thread.id,
            GeoCollaborationRead.user_id == user.id,
        )
    )
    if read is None:
        read = GeoCollaborationRead(
            workspace_id=workspace_id,
            thread_id=thread.id,
            user_id=user.id,
            read_at=utcnow(),
        )
        db.add(read)
    read.last_read_message_id = message.id
    read.read_at = utcnow()
    db.commit()
    return {
        "id": message.id,
        "thread_id": thread.id,
        "created_at": message.created_at,
        "message": _message_payload(message, users),
    }


@router.patch(
    "/workspaces/{workspace_id}/collaboration/contexts/{context_type}/{context_id}/work-info"
)
def update_collaboration_work_info(
    workspace_id: int,
    context_type: str,
    context_id: int,
    payload: WorkInfoUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_workspace_manager(db, user, workspace_id)
    if context_type not in CONTEXT_TYPES:
        raise HTTPException(status_code=422, detail="不支持的任务对象")
    context = _context_or_404(db, workspace_id, context_type, context_id)
    active_members = {
        membership.user_id: membership
        for membership in db.scalars(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.status == "active",
            )
        )
    }
    participant_ids = sorted(set(payload.participant_user_ids))
    candidate_ids = set(participant_ids)
    if payload.assignee_user_id:
        candidate_ids.add(payload.assignee_user_id)
    if any(value not in active_members for value in candidate_ids):
        raise HTTPException(status_code=422, detail="负责人或参与人不在当前工作区")
    if payload.assignee_user_id and active_members[payload.assignee_user_id].role == "viewer":
        raise HTTPException(status_code=422, detail="只读成员不能担任负责人")
    thread = _get_or_create_thread(
        db,
        workspace_id=workspace_id,
        context_type=context_type,
        context_id=context_id,
        context=context,
        user_id=user.id,
    )
    previous_assignee = thread.assignee_user_id
    previous_due_at = thread.due_at
    thread.assignee_user_id = payload.assignee_user_id
    thread.start_at = payload.start_at
    thread.due_at = payload.due_at
    thread.participant_user_ids = sorted(
        set(participant_ids) | {user.id} | ({payload.assignee_user_id} if payload.assignee_user_id else set())
    )
    if context_type == "action":
        action = context
        if action.assignee_user_id != payload.assignee_user_id:
            action.assignee_user_id = payload.assignee_user_id
            append_event(
                db,
                action=action,
                event_type="action_assigned",
                actor_user_id=user.id,
                from_stage=action.stage,
                to_stage=action.stage,
                detail={
                    "previous_assignee_user_id": previous_assignee,
                    "assignee_user_id": payload.assignee_user_id,
                    "reason": "从协作中心更新",
                },
            )
        if action.due_at != payload.due_at:
            action.due_at = payload.due_at
            append_event(
                db,
                action=action,
                event_type="action_rescheduled",
                actor_user_id=user.id,
                from_stage=action.stage,
                to_stage=action.stage,
                detail={
                    "previous_due_at": previous_due_at.isoformat() if previous_due_at else None,
                    "due_at": payload.due_at.isoformat() if payload.due_at else None,
                    "reason": "从协作中心更新",
                },
            )
    db.commit()
    return get_collaboration_center(
        workspace_id=workspace_id,
        context_type=context_type,
        context_id=context_id,
        db=db,
        user=user,
    )


@router.post("/workspaces/{workspace_id}/collaboration/threads/{thread_id}/read")
def mark_collaboration_read(
    workspace_id: int,
    thread_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_workspace_access(db, user, workspace_id)
    thread = db.get(GeoCollaborationThread, thread_id)
    if thread is None or thread.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    latest_id = db.scalar(
        select(func.max(GeoCollaborationMessage.id)).where(
            GeoCollaborationMessage.thread_id == thread.id
        )
    )
    state = db.scalar(
        select(GeoCollaborationRead).where(
            GeoCollaborationRead.thread_id == thread.id,
            GeoCollaborationRead.user_id == user.id,
        )
    )
    if state is None:
        state = GeoCollaborationRead(
            workspace_id=workspace_id,
            thread_id=thread.id,
            user_id=user.id,
            read_at=utcnow(),
        )
        db.add(state)
    state.last_read_message_id = latest_id
    state.read_at = utcnow()
    db.commit()
    return {"thread_id": thread.id, "last_read_message_id": latest_id, "read_at": state.read_at}


@router.put("/workspaces/{workspace_id}/collaboration/channels/{provider}")
def configure_collaboration_channel(
    workspace_id: int,
    provider: str,
    payload: ChannelConfigure,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_workspace_manager(db, user, workspace_id)
    if provider not in CHANNEL_PROVIDERS or payload.provider != provider:
        raise HTTPException(status_code=422, detail="渠道类型不匹配")
    row = db.scalar(
        select(GeoCollaborationChannel).where(
            GeoCollaborationChannel.workspace_id == workspace_id,
            GeoCollaborationChannel.provider == provider,
        )
    )
    raw_credentials = {
        "webhook_url": str(payload.webhook_url) if payload.webhook_url else "",
        "corp_id": payload.corp_id or "",
        "app_id": payload.app_id or "",
        "app_key": payload.app_key or "",
        "agent_id": payload.agent_id or "",
        "app_secret": payload.app_secret.get_secret_value() if payload.app_secret else "",
    }
    credentials = {
        key: value.strip()
        for key, value in raw_credentials.items()
        if value and value.strip()
    }
    # Editing a verified connection must not force an administrator to paste its
    # secret again. Only reuse encrypted values when the connection mode is
    # unchanged; switching mode always requires that mode's complete credential set.
    effective_credentials = dict(credentials)
    if row is not None and row.connection_mode == payload.connection_mode:
        stored_credentials = _channel_credentials(
            db, workspace_id, provider, payload.connection_mode
        )
        effective_credentials = {**stored_credentials, **credentials}
    try:
        configured_fields = validate_configuration(
            provider, payload.connection_mode, effective_credentials
        )
    except OfficeProviderError as exc:
        raise _office_http_error(exc) from exc
    for field in configured_fields:
        if field not in credentials:
            continue
        set_workspace_secret(
            db,
            workspace_id=workspace_id,
            key=_credential_key(provider, payload.connection_mode, field),
            value=credentials[field],
            user_id=user.id,
        )
    if row is None:
        row = GeoCollaborationChannel(workspace_id=workspace_id, provider=provider)
        db.add(row)
    row.status = "configured"
    row.display_name = payload.display_name or CHANNEL_LABELS[provider]
    row.connection_mode = payload.connection_mode
    row.configured_fields = configured_fields
    row.capabilities = CAPABILITIES[provider][payload.connection_mode]
    row.deep_link_base_url = (
        str(payload.deep_link_base_url).rstrip("/") if payload.deep_link_base_url else None
    )
    row.configured_by_user_id = user.id
    row.configured_at = utcnow()
    row.last_error_code = None
    db.commit()
    return next(item for item in _channels(db, workspace_id) if item["provider"] == provider)


@router.post("/workspaces/{workspace_id}/collaboration/channels/{provider}/test")
def test_collaboration_channel(
    workspace_id: int,
    provider: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_workspace_manager(db, user, workspace_id)
    if provider not in CHANNEL_PROVIDERS:
        raise HTTPException(status_code=422, detail="不支持的渠道")
    row = db.scalar(
        select(GeoCollaborationChannel).where(
            GeoCollaborationChannel.workspace_id == workspace_id,
            GeoCollaborationChannel.provider == provider,
        )
    )
    if row is None:
        raise HTTPException(status_code=409, detail="请先保存渠道配置")
    credentials = _channel_credentials(db, workspace_id, provider, row.connection_mode)
    try:
        test_office_connection(provider, row.connection_mode, credentials)
    except OfficeProviderError as exc:
        row.status = "error"
        row.last_tested_at = utcnow()
        row.last_error_code = exc.code[:80]
        db.commit()
        raise _office_http_error(exc) from exc
    row.status = "connected"
    row.last_tested_at = utcnow()
    row.last_error_code = None
    db.commit()
    return next(item for item in _channels(db, workspace_id) if item["provider"] == provider)


def _active_member(db: Session, workspace_id: int, user_id: int) -> WorkspaceMembership:
    membership = db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.status == "active",
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="协作成员不存在")
    return membership


@router.put(
    "/workspaces/{workspace_id}/collaboration/members/{member_id}/bindings/{provider}"
)
def bind_collaboration_member(
    workspace_id: int,
    member_id: int,
    provider: str,
    payload: MemberBindingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_workspace_manager(db, user, workspace_id)
    _active_member(db, workspace_id, member_id)
    if provider not in CHANNEL_PROVIDERS:
        raise HTTPException(status_code=422, detail="不支持的渠道")
    channel = db.scalar(
        select(GeoCollaborationChannel).where(
            GeoCollaborationChannel.workspace_id == workspace_id,
            GeoCollaborationChannel.provider == provider,
        )
    )
    if channel is None or channel.status != "connected" or channel.connection_mode != "app":
        raise HTTPException(status_code=409, detail="请先连接该平台的企业自建应用")
    credentials = _channel_credentials(db, workspace_id, provider, "app")
    try:
        verified = verify_office_member(
            provider,
            credentials,
            payload.external_user_id.strip(),
            payload.external_id_type,
        )
    except OfficeProviderError as exc:
        raise _office_http_error(exc) from exc
    row = db.scalar(
        select(GeoCollaborationMemberBinding).where(
            GeoCollaborationMemberBinding.workspace_id == workspace_id,
            GeoCollaborationMemberBinding.user_id == member_id,
            GeoCollaborationMemberBinding.provider == provider,
        )
    )
    if row is None:
        row = GeoCollaborationMemberBinding(
            workspace_id=workspace_id, user_id=member_id, provider=provider
        )
        db.add(row)
    row.external_user_id = str(verified["external_user_id"])
    row.external_id_type = payload.external_id_type
    row.external_display_name = verified["external_display_name"]
    row.status = "verified"
    row.verified_at = utcnow()
    row.verified_by_user_id = user.id
    db.commit()
    return next(
        item
        for item in _members(db, workspace_id, user)
        if item["id"] == member_id
    )


@router.put(
    "/workspaces/{workspace_id}/collaboration/members/{member_id}/notification-preferences"
)
def update_collaboration_notification_preferences(
    workspace_id: int,
    member_id: int,
    payload: NotificationPreferenceUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_workspace_manager(db, user, workspace_id)
    _active_member(db, workspace_id, member_id)
    row = db.scalar(
        select(GeoCollaborationNotificationPreference).where(
            GeoCollaborationNotificationPreference.workspace_id == workspace_id,
            GeoCollaborationNotificationPreference.user_id == member_id,
        )
    )
    if row is None:
        row = GeoCollaborationNotificationPreference(
            workspace_id=workspace_id, user_id=member_id
        )
        db.add(row)
    row.provider_settings = dict(payload.provider_settings)
    row.event_types = list(dict.fromkeys(payload.event_types))
    row.updated_by_user_id = user.id
    db.commit()
    return next(
        item
        for item in _members(db, workspace_id, user)
        if item["id"] == member_id
    )


def _notification_snapshot(
    db: Session, workspace_id: int, context_type: str, context_id: int, note: str
) -> dict:
    context = _context_or_404(db, workspace_id, context_type, context_id)
    if context_type == "action":
        progress, completed, total = _action_progress(db, context)
        snapshot = {
            "title": context.title,
            "category": ACTION_TYPE_LABELS.get(context.action_type, "优化行动"),
            "status": context.stage,
            "progress": progress,
            "summary": context.blocked_note or context.rationale or "",
            "detail": f"{completed}/{total} 个交付对象" if total else f"{progress}% 进度",
            "relative_url": f"/geo/{workspace_id}/actions?action_id={context.id}",
        }
    elif context_type == "alert":
        snapshot = {
            "title": context.title,
            "category": "变化告警",
            "status": context.status,
            "progress": 100 if context.status == "resolved" else 0,
            "summary": context.summary or "",
            "detail": context.severity,
            "relative_url": f"/geo/{workspace_id}/alerts",
        }
    elif context_type == "question":
        snapshot = {
            "title": context.question_text,
            "category": "问题讨论",
            "status": context.status,
            "progress": 0,
            "summary": context.source_reason or "",
            "detail": f"重要性 {context.importance}/5",
            "relative_url": f"/geo/{workspace_id}/questions/{context.id}",
        }
    else:
        question = db.get(GeoQuestionPlan, context.question_plan_id)
        snapshot = {
            "title": question.question_text if question else f"观测结果 #{context.id}",
            "category": f"观测洞察 · {context.model_label}",
            "status": context.brand_status,
            "progress": 100,
            "summary": (context.answer_text or "")[:500],
            "detail": f"{len(context.source_items or [])} 条引用来源",
            "relative_url": f"/geo/{workspace_id}/evidence/{context.id}",
        }
    snapshot["note"] = note.strip()
    return snapshot


def _preference_for(
    db: Session, workspace_id: int, user_id: int
) -> GeoCollaborationNotificationPreference | None:
    return db.scalar(
        select(GeoCollaborationNotificationPreference).where(
            GeoCollaborationNotificationPreference.workspace_id == workspace_id,
            GeoCollaborationNotificationPreference.user_id == user_id,
        )
    )


def _binding_for(
    db: Session, workspace_id: int, user_id: int, provider: str
) -> GeoCollaborationMemberBinding | None:
    return db.scalar(
        select(GeoCollaborationMemberBinding).where(
            GeoCollaborationMemberBinding.workspace_id == workspace_id,
            GeoCollaborationMemberBinding.user_id == user_id,
            GeoCollaborationMemberBinding.provider == provider,
            GeoCollaborationMemberBinding.status == "verified",
        )
    )


def _notification_readiness(
    db: Session,
    workspace_id: int,
    recipient_user_id: int,
    event_type: str,
    providers: list[str],
) -> list[dict]:
    channels = {
        row.provider: row
        for row in db.scalars(
            select(GeoCollaborationChannel).where(
                GeoCollaborationChannel.workspace_id == workspace_id
            )
        )
    }
    preference = _preference_for(db, workspace_id, recipient_user_id)
    provider_settings = dict(preference.provider_settings or {}) if preference else {}
    event_types = set(preference.event_types or []) if preference else set()
    result = []
    for provider in providers:
        channel = channels.get(provider)
        reason = None
        binding = None
        if channel is None or channel.status != "connected":
            reason = "平台尚未连接"
        elif not provider_settings.get(provider, False):
            reason = "该成员已关闭此平台通知"
        elif event_type not in event_types:
            reason = "该成员已关闭此类通知"
        elif channel.connection_mode == "app":
            binding = _binding_for(db, workspace_id, recipient_user_id, provider)
            if binding is None:
                reason = "成员尚未绑定该平台账号"
        result.append(
            {
                "provider": provider,
                "label": PROVIDER_LABELS[provider],
                "ready": reason is None,
                "reason": reason,
                "connection_mode": channel.connection_mode if channel else None,
                "identity_verified": bool(binding) if channel and channel.connection_mode == "app" else None,
                "status_fact": "发送后仅能确认平台是否接受请求",
            }
        )
    return result


def _message_text(snapshot: dict, deep_link_base_url: str | None) -> str:
    lines = [
        f"【{snapshot['category']}】{snapshot['title']}",
        f"状态：{snapshot['status']} · {snapshot['progress']}%",
    ]
    if snapshot.get("detail"):
        lines.append(str(snapshot["detail"]))
    if snapshot.get("summary"):
        lines.append(str(snapshot["summary"])[:300])
    if snapshot.get("note"):
        lines.append(f"补充：{snapshot['note']}")
    if deep_link_base_url:
        lines.append(f"在 GEO 查看详情：{deep_link_base_url}{snapshot['relative_url']}")
    else:
        lines.append("请在春秋元泉 GEO 工作区查看详细证据。")
    return "\n".join(lines)


@router.post("/workspaces/{workspace_id}/collaboration/notifications/preview")
def preview_collaboration_notification(
    workspace_id: int,
    payload: NotificationPreviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_workspace_access(db, user, workspace_id)
    _active_member(db, workspace_id, payload.recipient_user_id)
    snapshot = _notification_snapshot(
        db, workspace_id, payload.context_type, payload.context_id, payload.note
    )
    providers = list(dict.fromkeys(payload.providers or list(CHANNEL_PROVIDERS)))
    readiness = _notification_readiness(
        db, workspace_id, payload.recipient_user_id, payload.event_type, providers
    )
    return {
        "recipient_user_id": payload.recipient_user_id,
        "event_type": payload.event_type,
        "snapshot": snapshot,
        "providers": readiness,
        "message_preview": _message_text(snapshot, None),
        "external_write_performed": False,
    }


@router.post("/workspaces/{workspace_id}/collaboration/notifications/send")
def send_collaboration_notification(
    workspace_id: int,
    payload: NotificationSendRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_workspace_access(db, user, workspace_id)
    _active_member(db, workspace_id, payload.recipient_user_id)
    snapshot = _notification_snapshot(
        db, workspace_id, payload.context_type, payload.context_id, payload.note
    )
    providers = list(dict.fromkeys(payload.providers))
    if not providers:
        raise HTTPException(status_code=422, detail="至少选择一个通知平台")
    readiness = _notification_readiness(
        db, workspace_id, payload.recipient_user_id, payload.event_type, providers
    )
    blockers = [item for item in readiness if not item["ready"]]
    if blockers:
        detail = "；".join(f"{item['label']}：{item['reason']}" for item in blockers)
        raise HTTPException(status_code=409, detail=detail)
    settings = get_settings()
    retry_after = consume_security_rate_limit(
        db,
        scope="collaboration-notification-sender",
        identity=f"{workspace_id}:{user.id}:{payload.recipient_user_id}",
        limit=settings.collaboration_notification_rate_limit_per_hour,
        window=timedelta(hours=1),
    )
    workspace_retry_after = consume_security_rate_limit(
        db,
        scope="collaboration-notification-workspace",
        identity=str(workspace_id),
        limit=settings.collaboration_notification_daily_workspace_limit,
        window=timedelta(days=1),
    )
    db.commit()
    blocked_for = max(retry_after, workspace_retry_after)
    if blocked_for:
        raise HTTPException(
            status_code=429,
            detail="办公平台通知已达到发送上限，请稍后重试",
            headers={"Retry-After": str(blocked_for)},
        )
    channels = {
        row.provider: row
        for row in db.scalars(
            select(GeoCollaborationChannel).where(
                GeoCollaborationChannel.workspace_id == workspace_id,
                GeoCollaborationChannel.provider.in_(providers),
            )
        )
    }
    results = []
    for provider in providers:
        duplicate = db.scalar(
            select(GeoCollaborationDelivery).where(
                GeoCollaborationDelivery.workspace_id == workspace_id,
                GeoCollaborationDelivery.provider == provider,
                GeoCollaborationDelivery.idempotency_key == payload.idempotency_key,
            )
        )
        if duplicate:
            results.append(_delivery_payload(duplicate))
            continue
        channel = channels[provider]
        binding = _binding_for(db, workspace_id, payload.recipient_user_id, provider)
        row = GeoCollaborationDelivery(
            workspace_id=workspace_id,
            recipient_user_id=payload.recipient_user_id,
            provider=provider,
            connection_mode=channel.connection_mode,
            context_type=payload.context_type,
            context_id=payload.context_id,
            event_type=payload.event_type,
            status="sending",
            message_snapshot=snapshot,
            provider_response={},
            idempotency_key=payload.idempotency_key,
            requested_by_user_id=user.id,
            attempted_at=utcnow(),
        )
        db.add(row)
        db.flush()
        try:
            result = send_office_message(
                provider,
                channel.connection_mode,
                _channel_credentials(db, workspace_id, provider, channel.connection_mode),
                text=_message_text(snapshot, channel.deep_link_base_url),
                external_user_id=binding.external_user_id if binding else None,
                external_id_type=binding.external_id_type if binding else "user_id",
            )
            row.status = "provider_accepted"
            row.provider_message_ref = result.provider_message_ref
            row.provider_response = result.evidence
            row.accepted_at = utcnow()
        except OfficeProviderError as exc:
            row.status = "failed"
            row.error_code = exc.code[:120]
            row.provider_response = {"message": exc.user_message}
        db.commit()
        results.append(_delivery_payload(row))
    return {
        "recipient_user_id": payload.recipient_user_id,
        "results": results,
        "truth_note": "provider_accepted 仅表示官方平台接受了请求，不代表成员已读。",
    }
