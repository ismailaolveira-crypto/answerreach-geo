from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
import re
from typing import Literal
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, HttpUrl, model_validator
from sqlalchemy import func, select
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
)
from app.models.collaboration import (
    GeoCollaborationAttachment,
    GeoCollaborationChannel,
    GeoCollaborationMessage,
    GeoCollaborationRead,
    GeoCollaborationThread,
)
from app.models.user import User
from app.models.workspace_access import WorkspaceMembership
from app.services.workspace_access import require_workspace_access, require_workspace_manager
from app.services.workspace_secrets import get_workspace_secret, set_workspace_secret
from app.v1.action_workflow import TARGET_WORKFLOWS, append_event


router = APIRouter(prefix="/v1", tags=["collaboration-center"])

CONTEXT_TYPES = {"action", "alert", "question", "evidence"}
CHANNEL_PROVIDERS = {"wecom", "feishu", "dingtalk"}
CHANNEL_LABELS = {"wecom": "企业微信", "feishu": "飞书", "dingtalk": "钉钉"}
CHANNEL_HOSTS = {
    "wecom": {"qyapi.weixin.qq.com"},
    "feishu": {"open.feishu.cn"},
    "dingtalk": {"oapi.dingtalk.com"},
}
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
    webhook_url: HttpUrl
    display_name: str | None = Field(default=None, max_length=120)


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
    return members


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
    """Build conversation summaries in two queries instead of querying every row."""
    thread_ids = [thread.id for thread in threads.values()]
    if not thread_ids:
        return {}
    reads = {
        row.thread_id: row
        for row in db.scalars(
            select(GeoCollaborationRead).where(
                GeoCollaborationRead.thread_id.in_(thread_ids),
                GeoCollaborationRead.user_id == current_user_id,
            )
        )
    }
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
    messages = list(
        db.scalars(
            select(GeoCollaborationMessage)
            .where(GeoCollaborationMessage.thread_id.in_(thread_ids))
            .order_by(GeoCollaborationMessage.id.asc())
        )
    )
    for message in messages:
        summary = stats[message.thread_id]
        summary["message_count"] += 1
        summary["last_message_preview"] = (
            message.body.strip()
            or ("[附件]" if message.attachment_refs else "[消息]")
        )[:120]
        summary["last_message_author_name"] = user_names.get(
            message.author_user_id or 0, "系统"
        )
        mentioned = current_user_id in (message.mention_user_ids or [])
        summary["mentioned_current_user"] = (
            summary["mentioned_current_user"] or mentioned
        )
        read = reads.get(message.thread_id)
        last_read_id = read.last_read_message_id if read else None
        if (
            message.author_user_id != current_user_id
            and (last_read_id is None or message.id > last_read_id)
        ):
            summary["unread_count"] += 1
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
            "configured_at": configured[provider].configured_at if provider in configured else None,
            "last_tested_at": configured[provider].last_tested_at if provider in configured else None,
            "last_error_code": configured[provider].last_error_code if provider in configured else None,
        }
        for provider in ("wecom", "feishu", "dingtalk")
    ]


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


def _validate_channel_url(provider: str, value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in CHANNEL_HOSTS[provider]:
        raise HTTPException(status_code=422, detail="请使用该平台官方 HTTPS 机器人地址")


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
    webhook_url = str(payload.webhook_url)
    _validate_channel_url(provider, webhook_url)
    set_workspace_secret(
        db,
        workspace_id=workspace_id,
        key=f"collaboration_{provider}_webhook_url",
        value=webhook_url,
        user_id=user.id,
    )
    row = db.scalar(
        select(GeoCollaborationChannel).where(
            GeoCollaborationChannel.workspace_id == workspace_id,
            GeoCollaborationChannel.provider == provider,
        )
    )
    if row is None:
        row = GeoCollaborationChannel(workspace_id=workspace_id, provider=provider)
        db.add(row)
    row.status = "configured"
    row.display_name = payload.display_name or CHANNEL_LABELS[provider]
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
    webhook_url = get_workspace_secret(
        db, workspace_id, f"collaboration_{provider}_webhook_url"
    )
    if row is None or not webhook_url:
        raise HTTPException(status_code=409, detail="请先保存渠道机器人地址")
    _validate_channel_url(provider, webhook_url)
    content = "春秋元泉 GEO 协作渠道已完成连接测试。"
    body = (
        {"msg_type": "text", "content": {"text": content}}
        if provider == "feishu"
        else {"msgtype": "text", "text": {"content": content}}
    )
    try:
        response = httpx.post(webhook_url, json=body, timeout=8.0)
        response.raise_for_status()
        result = response.json()
        success = (
            result.get("StatusCode") == 0
            if provider == "feishu"
            else result.get("errcode") == 0
        )
        if not success:
            raise RuntimeError("provider_rejected")
    except Exception as exc:
        row.status = "error"
        row.last_tested_at = utcnow()
        row.last_error_code = type(exc).__name__
        db.commit()
        raise HTTPException(status_code=502, detail="官方渠道未确认测试消息") from exc
    row.status = "connected"
    row.last_tested_at = utcnow()
    row.last_error_code = None
    db.commit()
    return next(item for item in _channels(db, workspace_id) if item["provider"] == provider)
