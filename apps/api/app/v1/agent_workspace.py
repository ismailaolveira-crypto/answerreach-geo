from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.cleanroom_v1 import (
    GeoAgentConversation,
    GeoAgentConversationEvent,
    GeoAgentConversationMessage,
    GeoEvidence,
    GeoObservationBatch,
    GeoObservationTask,
    GeoOptimizationAction,
    GeoQuestionPlan,
    GeoWorkspace,
)
from app.services.agent_runtime import get_agent_runtime, sanitize_agent_error


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "rationale_summary": {"type": "array", "items": {"type": "string"}},
        "evidence_summary": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"label": {"type": "string"}, "detail": {"type": "string"}},
                "required": ["label", "detail"],
                "additionalProperties": False,
            },
        },
        "execution_plan": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "status": {"type": "string", "enum": ["ready", "needs_user", "blocked"]},
                },
                "required": ["label", "status"],
                "additionalProperties": False,
            },
        },
        "suggested_action": {
            "type": ["object", "null"],
            "properties": {
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "action_type": {
                    "type": "string",
                    "enum": ["analysis", "article", "official_site", "structured_data", "third_party_source"],
                },
            },
            "required": ["title", "summary", "action_type"],
            "additionalProperties": False,
        },
        "needs_user": {"type": "boolean"},
    },
    "required": [
        "answer",
        "rationale_summary",
        "evidence_summary",
        "execution_plan",
        "suggested_action",
        "needs_user",
    ],
    "additionalProperties": False,
}


def add_event(
    db: Session,
    message: GeoAgentConversationMessage,
    event_type: str,
    stage: str,
    label: str,
    detail: dict | None = None,
) -> None:
    sequence = int(
        db.scalar(
            select(func.coalesce(func.max(GeoAgentConversationEvent.sequence), 0)).where(
                GeoAgentConversationEvent.message_id == message.id
            )
        )
        or 0
    ) + 1
    db.add(
        GeoAgentConversationEvent(
            workspace_id=message.workspace_id,
            message_id=message.id,
            sequence=sequence,
            event_type=event_type,
            stage=stage,
            message=label,
            detail=detail or {},
        )
    )
    db.commit()


def _trusted_context(db: Session, conversation: GeoAgentConversation) -> dict:
    scope = dict(conversation.context_snapshot or {})
    workspace = db.get(GeoWorkspace, conversation.workspace_id)
    context: dict = {
        "workspace": {"id": workspace.id, "brand_name": workspace.brand_name},
        "scope": {
            "batch_id": scope.get("batch_id"),
            "question_plan_id": scope.get("question_plan_id"),
            "action_id": scope.get("action_id"),
            "model_keys": list(scope.get("model_keys") or []),
        },
    }
    if scope.get("batch_id"):
        batch = db.get(GeoObservationBatch, int(scope["batch_id"]))
        if batch and batch.workspace_id == conversation.workspace_id:
            context["batch"] = {
                "id": batch.id,
                "status": batch.status,
                "completed_tasks": batch.completed_tasks,
                "total_tasks": batch.total_tasks,
            }
    if scope.get("question_plan_id"):
        question = db.get(GeoQuestionPlan, int(scope["question_plan_id"]))
        if question and question.workspace_id == conversation.workspace_id:
            context["question"] = {"id": question.id, "text": question.question_text}
    if scope.get("action_id"):
        action = db.get(GeoOptimizationAction, int(scope["action_id"]))
        if action and action.workspace_id == conversation.workspace_id:
            context["action"] = {
                "id": action.id,
                "title": action.title,
                "status": action.status,
                "summary": action.summary,
            }

    evidence_stmt = select(GeoEvidence).where(
        GeoEvidence.workspace_id == conversation.workspace_id,
        GeoEvidence.is_real_provider_evidence.is_(True),
    )
    if scope.get("batch_id"):
        evidence_stmt = evidence_stmt.join(
            GeoObservationTask, GeoObservationTask.evidence_id == GeoEvidence.id
        ).where(GeoObservationTask.batch_id == int(scope["batch_id"]))
    if scope.get("question_plan_id"):
        evidence_stmt = evidence_stmt.where(
            GeoEvidence.question_plan_id == int(scope["question_plan_id"])
        )
    model_keys = list(scope.get("model_keys") or [])
    if model_keys:
        evidence_stmt = evidence_stmt.where(GeoEvidence.model_key.in_(model_keys))
    evidence = list(db.scalars(evidence_stmt.order_by(GeoEvidence.captured_at.desc()).limit(20)))
    context["evidence"] = [
        {
            "id": item.id,
            "model": item.model_label,
            "brand_status": item.brand_status,
            "brand_position": item.brand_position,
            "answer_excerpt": item.answer_text[:600],
            "source_count": len(item.source_items or []),
            "captured_at": item.captured_at.isoformat(),
        }
        for item in evidence
    ]
    context["evidence_count"] = len(evidence)
    return context


def execute_agent_workspace_message(
    db: Session, message: GeoAgentConversationMessage
) -> GeoAgentConversationMessage:
    conversation = db.get(GeoAgentConversation, message.conversation_id)
    if conversation is None:
        raise ValueError("Agent conversation not found")
    message.status = "running"
    db.add(message)
    db.commit()
    add_event(db, message, "context.preparing", "context", "正在读取当前 GEO 范围")

    try:
        context = _trusted_context(db, conversation)
        add_event(
            db,
            message,
            "context.prepared",
            "context",
            f"已绑定 {context['evidence_count']} 条真实观测证据",
            {"evidence_count": context["evidence_count"]},
        )
        history = list(
            db.scalars(
                select(GeoAgentConversationMessage)
                .where(
                    GeoAgentConversationMessage.conversation_id == conversation.id,
                    GeoAgentConversationMessage.id != message.id,
                    GeoAgentConversationMessage.status == "completed",
                )
                .order_by(GeoAgentConversationMessage.sequence.desc())
                .limit(12)
            )
        )
        history.reverse()
        prompt = json.dumps(
            {
                "request": message.content,
                "conversation_history": [
                    {"role": item.role, "content": item.content[:3000]} for item in history
                ],
                "trusted_geo_context": context,
            },
            ensure_ascii=False,
        )
        developer_instructions = (
            f"你是{context['workspace']['brand_name']} GEO 企业增长工作台的执行助手。只依据输入中的 trusted_geo_context 与明确标注的常识回答。"
            "不要展示隐藏思维链，只提供可核验的判断依据摘要。证据不足时 needs_user=true。"
            "不得声称内容已发布、平台已登录、草稿可见或 GEO 已改善，除非上下文包含对应真实证据。"
            "本对话只负责分析、规划和提出优化行动建议；不得点击外部平台最终发布按钮。"
            "回答使用简洁中文，并严格返回指定 JSON。"
        )
        runtime = get_agent_runtime(str(message.runtime_key or conversation.runtime_key))
        runtime_event_count = 0

        def on_started(thread_id: str, turn_id: str) -> None:
            conversation.external_thread_id = thread_id
            message.external_turn_id = turn_id
            db.add_all([conversation, message])
            db.commit()
            add_event(db, message, "runtime.started", "runtime", "Agent 已开始处理")

        def on_event(method: str, _detail: dict) -> None:
            nonlocal runtime_event_count
            if method not in {"turn/started", "item/started", "item/completed", "agent/cli_started"}:
                return
            if runtime_event_count >= 30:
                return
            runtime_event_count += 1
            labels = {
                "turn/started": "已建立本次执行",
                "item/started": "正在分析上下文",
                "item/completed": "完成一个处理步骤",
                "agent/cli_started": "已启动本机 Agent",
            }
            add_event(db, message, method, "runtime", labels[method])

        result = runtime.run_structured(
            task_directory=(
                Path(__file__).resolve().parents[4]
                / "private_artifacts"
                / "agent-workspace"
                / str(conversation.workspace_id)
                / str(conversation.id)
            ),
            prompt=prompt,
            output_schema=OUTPUT_SCHEMA,
            developer_instructions=developer_instructions,
            model=message.model,
            reasoning_effort=conversation.reasoning_effort,
            thread_id=conversation.external_thread_id,
            on_started=on_started,
            on_event=on_event,
        )
        payload = json.loads(result.final_response)
        answer = str(payload.get("answer") or "").strip()
        if not answer:
            raise ValueError("Agent response has no answer")
        payload["source_context"] = {
            "scope": context["scope"],
            "evidence_ids": [item["id"] for item in context["evidence"]],
            "evidence_count": context["evidence_count"],
        }
        message.content = answer
        message.structured_payload = payload
        message.status = "completed"
        message.external_turn_id = result.turn_id
        conversation.external_thread_id = result.thread_id
        conversation.last_message_at = datetime.now(UTC)
        db.add_all([message, conversation])
        db.commit()
        add_event(db, message, "response.validated", "complete", "回答已按 GEO 事实边界校验")
        return message
    except Exception as exc:
        message.status = "failed"
        message.error_message = sanitize_agent_error(exc)
        db.add(message)
        db.commit()
        add_event(db, message, "run.failed", "failed", "本次处理失败", {"error": message.error_message})
        raise
