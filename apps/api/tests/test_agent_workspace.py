import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.session import Base
from app.models.cleanroom_v1 import (
    GeoAgentConversation,
    GeoAgentConversationEvent,
    GeoAgentConversationMessage,
    GeoActionTarget,
    GeoOptimizationAction,
    GeoWorkspace,
)
from app.models.company import Company
from app.models.job import QueueJob
from app.models.user import User
from app.models.workspace_access import WorkspaceMembership
from app.services.job_queue import run_job
from app.v1 import agent_workspace
from app.v1 import agent_workspace_routes
from app.v1.agent_workspace_routes import _conversation_read


def test_agent_workspace_persists_structured_answer_and_readable_events(monkeypatch) -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)

    class FakeRuntime:
        def run_structured(self, **kwargs):
            kwargs["on_started"]("thread-1", "turn-1")
            kwargs["on_event"]("item/started", {})
            kwargs["on_event"]("item/completed", {})
            payload = {
                "answer": "先补齐当前问题的可引用解释页。",
                "rationale_summary": ["当前范围已绑定真实观测"],
                "evidence_summary": [],
                "execution_plan": [{"label": "建立优化行动", "status": "ready"}],
                "suggested_action": {
                    "title": "补齐解释页",
                    "summary": "进入优化行动后由负责人审核执行。",
                    "action_type": "content",
                },
                "needs_user": False,
            }
            return SimpleNamespace(
                thread_id="thread-1",
                turn_id="turn-1",
                final_response=json.dumps(payload, ensure_ascii=False),
            )

    monkeypatch.setattr(agent_workspace, "get_agent_runtime", lambda _key: FakeRuntime())
    with Session(engine, expire_on_commit=False) as db:
        db.add(Company(id=1, name="测试公司"))
        db.add(User(id=1, company_id=1, name="测试用户", email="agent@example.com", role="company_admin"))
        db.add(GeoWorkspace(id=1, company_id=1, slug="agent-workspace", brand_name="测试品牌", brand_aliases=[]))
        db.flush()
        conversation = GeoAgentConversation(workspace_id=1, created_by_user_id=1, title="测试会话", context_snapshot={})
        db.add(conversation)
        db.flush()
        message = GeoAgentConversationMessage(
            workspace_id=1,
            conversation_id=conversation.id,
            sequence=2,
            role="assistant",
            content="下一步做什么？",
            status="queued",
            runtime_key="local_codex",
        )
        db.add(message)
        db.commit()

        result = agent_workspace.execute_agent_workspace_message(db, message)

        assert result.status == "completed"
        assert result.content == "先补齐当前问题的可引用解释页。"
        assert result.structured_payload["suggested_action"]["title"] == "补齐解释页"
        assert conversation.external_thread_id == "thread-1"
        events = list(
            db.scalars(
                select(GeoAgentConversationEvent)
                .where(GeoAgentConversationEvent.message_id == message.id)
                .order_by(GeoAgentConversationEvent.sequence)
            )
        )
        assert [item.event_type for item in events] == [
            "context.preparing",
            "context.prepared",
            "runtime.started",
            "item/started",
            "item/completed",
            "response.validated",
        ]


def test_queue_failure_marks_agent_workspace_message_failed() -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add(Company(id=1, name="测试公司"))
        db.add(User(id=1, company_id=1, name="测试用户", email="queue@example.com", role="company_admin"))
        db.add(GeoWorkspace(id=1, company_id=1, slug="queue-workspace", brand_name="测试品牌", brand_aliases=[]))
        db.flush()
        conversation = GeoAgentConversation(workspace_id=1, created_by_user_id=1, title="队列失败", context_snapshot={})
        db.add(conversation)
        db.flush()
        job = QueueJob(job_type="geo_agent.conversation", status="running", attempts=1, max_attempts=1, payload_json={"workspace_id": 1})
        db.add(job)
        db.flush()
        message = GeoAgentConversationMessage(
            workspace_id=1,
            conversation_id=conversation.id,
            sequence=2,
            role="assistant",
            content="分析失败传播",
            status="queued",
            runtime_key="local_codex",
            job_id=job.id,
        )
        db.add(message)
        db.commit()

        run_job(db, job)

        db.refresh(message)
        assert job.status == "failed"
        assert message.status == "failed"
        assert message.error_message


def test_conversation_read_uses_failed_queue_job_as_authoritative_state() -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add(Company(id=1, name="测试公司"))
        db.add(User(id=1, company_id=1, name="测试用户", email="readback@example.com", role="company_admin"))
        db.add(GeoWorkspace(id=1, company_id=1, slug="readback-workspace", brand_name="测试品牌", brand_aliases=[]))
        db.flush()
        conversation = GeoAgentConversation(workspace_id=1, created_by_user_id=1, title="旧 Worker 失败", context_snapshot={})
        db.add(conversation)
        db.flush()
        job = QueueJob(
            job_type="geo_agent.conversation",
            status="failed",
            attempts=1,
            max_attempts=1,
            payload_json={"workspace_id": 1},
            error_message="Unsupported job type: geo_agent.conversation",
        )
        db.add(job)
        db.flush()
        db.add(
            GeoAgentConversationMessage(
                workspace_id=1,
                conversation_id=conversation.id,
                sequence=2,
                role="assistant",
                content="为什么很慢",
                status="queued",
                runtime_key="local_codex",
                job_id=job.id,
            )
        )
        db.commit()

        payload = _conversation_read(db, conversation, include_messages=True)

        assert payload["last_message_status"] == "failed"
        assert payload["messages"][0]["status"] == "failed"
        assert payload["messages"][0]["error_message"] == "后台 Worker 版本过旧，请执行一键修复后重试"


def test_failed_queue_job_does_not_block_next_conversation_turn(monkeypatch) -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        agent_workspace_routes,
        "diagnose_agent_runtime",
        lambda _runtime_key: {
            "ready": True,
            "available_models": ["test-model"],
            "default_model": "test-model",
            "default_reasoning_effort": "low",
        },
    )
    with Session(engine, expire_on_commit=False) as db:
        company = Company(id=1, name="测试公司")
        user = User(id=1, company_id=1, name="管理员", email="retry@example.com", role="super_admin")
        workspace = GeoWorkspace(id=1, company_id=1, slug="retry-workspace", brand_name="测试品牌", brand_aliases=[])
        db.add_all([company, user, workspace])
        db.flush()
        conversation = GeoAgentConversation(workspace_id=1, created_by_user_id=1, title="可重试会话", context_snapshot={})
        db.add(conversation)
        db.flush()
        failed_job = QueueJob(
            job_type="geo_agent.conversation",
            status="failed",
            attempts=1,
            max_attempts=1,
            payload_json={"workspace_id": 1},
            error_message="旧 Worker 不支持任务",
        )
        db.add(failed_job)
        db.flush()
        db.add(
            GeoAgentConversationMessage(
                workspace_id=1,
                conversation_id=conversation.id,
                sequence=2,
                role="assistant",
                content="第一次请求",
                status="queued",
                runtime_key="local_codex",
                job_id=failed_job.id,
            )
        )
        db.commit()

        payload = agent_workspace_routes.create_agent_workspace_message(
            1,
            conversation.id,
            agent_workspace_routes.MessageCreate(content="重新执行", runtime_key="local_codex"),
            db,
            user,
        )

        assert payload["last_message_status"] == "queued"
        assert payload["messages"][-1]["job_id"] != failed_job.id


def test_agent_suggestion_creates_one_real_action_and_reuses_it() -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine, expire_on_commit=False) as db:
        db.add(Company(id=1, name="测试公司"))
        user = User(id=1, company_id=1, name="管理员", email="action@example.com", role="company_admin")
        db.add(user)
        db.add(GeoWorkspace(id=1, company_id=1, slug="action-workspace", brand_name="测试品牌", brand_aliases=[]))
        db.flush()
        db.add(WorkspaceMembership(workspace_id=1, user_id=1, role="owner", status="active", joined_at=now))
        conversation = GeoAgentConversation(
            workspace_id=1,
            created_by_user_id=1,
            title="分析机会",
            context_snapshot={"model_keys": ["glm"]},
        )
        db.add(conversation)
        db.flush()
        message = GeoAgentConversationMessage(
            workspace_id=1,
            conversation_id=conversation.id,
            sequence=2,
            role="assistant",
            content="建议先分析候选第 5 位的提升空间。",
            status="completed",
            structured_payload={
                "suggested_action": {
                    "title": "分析候选第 5 位的提升空间",
                    "summary": "对比模型回答，形成优先优化清单。",
                    "action_type": "geo_evidence_analysis",
                }
            },
        )
        db.add(message)
        db.commit()

        request = agent_workspace_routes.SuggestionActionCreate(
            title="分析候选第 5 位的提升空间",
            expected_goal="产出可审核的提升清单和证据摘要。",
            assignee_user_id=1,
            due_at=now + timedelta(days=7),
        )
        first = agent_workspace_routes.create_agent_suggestion_action(
            1, conversation.id, message.id, request, db, user
        )
        second = agent_workspace_routes.create_agent_suggestion_action(
            1, conversation.id, message.id, request, db, user
        )

        assert first == {"action_id": first["action_id"], "created": True}
        assert second == {"action_id": first["action_id"], "created": False}
        action = db.get(GeoOptimizationAction, first["action_id"])
        target = db.scalar(select(GeoActionTarget).where(GeoActionTarget.action_id == action.id))
        db.refresh(message)
        assert action.action_type == "analysis"
        assert action.assignee_user_id == 1
        assert action.affected_model_keys == ["glm"]
        assert target.target_type == "analysis_deliverable"
        assert target.delivery_status == "scope_confirmed"
        assert message.structured_payload["linked_action_id"] == action.id
