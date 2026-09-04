from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.session import Base, get_db
from app.main import create_app
from app.models.cleanroom_v1 import (
    GeoActionTarget,
    GeoAgentConversation,
    GeoAgentConversationMessage,
    GeoAgentRun,
    GeoOptimizationAction,
    GeoReobservation,
    GeoWorkspace,
)
from app.models.company import Company
from app.models.job import QueueJob
from app.models.project import Project
from app.models.user import User
from app.services.auth import hash_password, issue_access_token
from app.services.job_queue import claim_next_job, recover_orphaned_jobs
from app.services.workspace_access import add_membership
from app.v1.action_workflow import derive_delivery_stage
from app.v1.agent_run_routes import _agent_capacity
from app.v1.agent_workspace import agent_workspace_artifact_root


def _memory_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def issue27_api() -> Generator[tuple[TestClient, sessionmaker[Session], dict], None, None]:
    engine = _memory_engine()
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with sessions() as db:
        company_a = Company(id=1, name="Tenant A", brand_aliases=[])
        company_b = Company(id=2, name="Tenant B", brand_aliases=[])
        db.add_all([company_a, company_b])
        db.flush()
        admin_a = User(
            id=1,
            company_id=1,
            name="Admin A",
            email="a-admin@example.com",
            password_hash=hash_password("password-a-admin"),
            role="company_admin",
            status="active",
        )
        admin_b = User(
            id=2,
            company_id=2,
            name="Admin B",
            email="b-admin@example.com",
            password_hash=hash_password("password-b-admin"),
            role="company_admin",
            status="active",
        )
        invited = User(
            id=3,
            company_id=None,
            name="Invited Reviewer",
            email="reviewer@example.com",
            password_hash=hash_password("password-reviewer"),
            role="viewer",
            status="active",
        )
        db.add_all([admin_a, admin_b, invited])
        db.flush()
        workspace_a = GeoWorkspace(
            id=1,
            company_id=1,
            slug="tenant-a",
            brand_name="Brand A",
            brand_aliases=[],
        )
        workspace_b = GeoWorkspace(
            id=2,
            company_id=2,
            slug="tenant-b",
            brand_name="Brand B",
            brand_aliases=[],
        )
        db.add_all([workspace_a, workspace_b])
        db.flush()
        db.add(Project(id=1, company_id=2, name="Tenant B first project"))
        add_membership(db, workspace_id=1, user_id=1, role="owner")
        add_membership(db, workspace_id=2, user_id=2, role="owner")
        add_membership(db, workspace_id=1, user_id=3, role="reviewer")
        token_a = issue_access_token(db, admin_a)
        token_b = issue_access_token(db, admin_b)
        token_reviewer = issue_access_token(db, invited)
        db.commit()
        ids = {
            "token_a": token_a,
            "token_b": token_b,
            "token_reviewer": token_reviewer,
            "workspace_a": workspace_a.id,
            "company_a": company_a.id,
            "company_b": company_b.id,
        }

    def override_db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(app), sessions, ids
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_queue_does_not_treat_workspace_id_as_project_id(issue27_api) -> None:
    client, sessions, ids = issue27_api
    now = datetime.now(UTC)
    with sessions() as db:
        db.add(
            QueueJob(
                job_type="geo_observation.collect",
                status="pending",
                priority=10,
                scheduled_at=now,
                payload_json={
                    "dispatch_enabled": True,
                    "workspace_id": 1,
                    "project_id": 1,
                    "company_id": 1,
                    "question_label": "tenant-a-secret-question",
                },
            )
        )
        db.commit()

    listed = client.get("/api/queue/jobs", headers=_auth(ids["token_b"]))
    assert listed.status_code == 200, listed.text
    jobs = listed.json()["jobs"]
    assert jobs == []
    assert listed.json()["summary"]["pending"] == 0

    ran = client.post("/api/queue/jobs/run-next", headers=_auth(ids["token_b"]))
    assert ran.status_code == 200, ran.text
    assert ran.json()["ran"] is False
    with sessions() as db:
        leftover = db.scalar(select(QueueJob))
        assert leftover is not None
        assert leftover.status == "pending"


def test_recover_orphaned_agent_run_and_recovering_jobs() -> None:
    engine = _memory_engine()
    now = datetime.now(UTC)
    stale = now - timedelta(seconds=180)
    with Session(engine) as db:
        db.add(Company(id=1, name="Tenant A", brand_aliases=[]))
        db.add(User(id=1, company_id=1, name="Admin", email="a@example.com", role="company_admin"))
        db.add(GeoWorkspace(id=1, company_id=1, slug="a", brand_name="A", brand_aliases=[]))
        db.add(
            GeoOptimizationAction(
                id=1,
                workspace_id=1,
                title="run",
                rationale="r",
                priority="high",
                status="in_progress",
                stage="generating",
            )
        )
        db.flush()
        run_job = QueueJob(
            job_type="geo_agent.run",
            status="running",
            attempts=1,
            max_attempts=1,
            scheduled_at=stale,
            started_at=stale,
            payload_json={"workspace_id": 1, "company_id": 1, "agent_run_id": 1, "worker_id": "dead"},
        )
        recovering_job = QueueJob(
            job_type="geo_agent.conversation",
            status="recovering",
            attempts=1,
            max_attempts=1,
            scheduled_at=stale,
            started_at=stale,
            payload_json={"workspace_id": 1, "company_id": 1, "worker_id": "dead"},
        )
        db.add_all([run_job, recovering_job])
        db.flush()
        db.add(
            GeoAgentRun(
                id=1,
                workspace_id=1,
                action_id=1,
                job_id=run_job.id,
                runtime_key="local_codex",
                status="running",
                stage="running",
                selected_platforms=["zhihu"],
                request_snapshot={},
            )
        )
        conversation = GeoAgentConversation(
            workspace_id=1,
            created_by_user_id=1,
            title="对话",
            context_snapshot={},
        )
        db.add(conversation)
        db.flush()
        db.add(
            GeoAgentConversationMessage(
                workspace_id=1,
                conversation_id=conversation.id,
                sequence=1,
                role="assistant",
                content="q",
                status="running",
                job_id=recovering_job.id,
            )
        )
        db.commit()
        result = recover_orphaned_jobs(db, now=now)
        assert result["failed"] >= 1
        db.expire_all()
        run = db.get(GeoAgentRun, 1)
        message = db.scalar(select(GeoAgentConversationMessage))
        leftover_recovering = db.scalar(
            select(QueueJob).where(QueueJob.status == "recovering")
        )
        assert run is not None
        assert run.status == "failed"
        assert message is not None
        assert message.status == "failed"
        assert leftover_recovering is None


def test_stale_queued_message_with_finished_job_does_not_occupy_capacity() -> None:
    engine = _memory_engine()
    now = datetime.now(UTC)
    with Session(engine) as db:
        db.add(Company(id=1, name="Tenant A", brand_aliases=[]))
        db.add(User(id=1, company_id=1, name="Admin", email="a@example.com", role="company_admin"))
        db.add(GeoWorkspace(id=1, company_id=1, slug="a", brand_name="A", brand_aliases=[]))
        conversation = GeoAgentConversation(
            workspace_id=1,
            created_by_user_id=1,
            title="对话",
            context_snapshot={},
        )
        db.add(conversation)
        db.flush()
        finished_job = QueueJob(
            job_type="geo_agent.conversation",
            status="success",
            scheduled_at=now,
            payload_json={"workspace_id": 1, "company_id": 1},
        )
        db.add(finished_job)
        db.flush()
        db.add(
            GeoAgentConversationMessage(
                workspace_id=1,
                conversation_id=conversation.id,
                sequence=1,
                role="assistant",
                content="stale",
                status="queued",
                job_id=finished_job.id,
            )
        )
        db.commit()
        _limit, active_count, _busy = _agent_capacity(db, 1)
        assert active_count == 0


def test_capacity_counts_conversations_and_discovery_together() -> None:
    engine = _memory_engine()
    now = datetime.now(UTC)
    with Session(engine) as db:
        db.add(Company(id=1, name="Tenant A", brand_aliases=[]))
        db.add(User(id=1, company_id=1, name="Admin", email="a@example.com", role="company_admin"))
        db.add(GeoWorkspace(id=1, company_id=1, slug="a", brand_name="A", brand_aliases=[]))
        db.add(
            GeoOptimizationAction(
                id=1,
                workspace_id=1,
                title="run",
                rationale="r",
                priority="high",
                status="in_progress",
                stage="generating",
            )
        )
        db.flush()
        db.add(
            GeoAgentRun(
                workspace_id=1,
                action_id=1,
                runtime_key="local_codex",
                status="queued",
                stage="queued",
                selected_platforms=["zhihu"],
                request_snapshot={},
            )
        )
        conversation = GeoAgentConversation(
            workspace_id=1,
            created_by_user_id=1,
            title="对话",
            context_snapshot={},
        )
        db.add(conversation)
        db.flush()
        db.add(
            GeoAgentConversationMessage(
                workspace_id=1,
                conversation_id=conversation.id,
                sequence=1,
                role="assistant",
                content="q",
                status="queued",
            )
        )
        db.add(
            QueueJob(
                job_type="geo_opportunity.discover",
                status="pending",
                scheduled_at=now,
                payload_json={"workspace_id": 1, "company_id": 1, "input_fingerprint": "abc"},
            )
        )
        db.commit()
        limit, active_count, _busy = _agent_capacity(db, 1)
        assert limit == 10
        assert active_count == 3


def test_invited_reviewer_can_mutate_workspace_routes(issue27_api) -> None:
    client, _sessions, ids = issue27_api
    created = client.post(
        f"/api/v1/workspaces/{ids['workspace_a']}/agent-workspace/conversations",
        headers=_auth(ids["token_reviewer"]),
        json={"title": "审稿对话"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["title"] == "审稿对话"


def test_claim_loses_to_cas_cancel() -> None:
    engine = _memory_engine()
    now = datetime.now(UTC)
    with Session(engine) as db:
        job = QueueJob(
            job_type="geo_agent.run",
            status="pending",
            scheduled_at=now,
            payload_json={"workspace_id": 1, "company_id": 1},
        )
        db.add(job)
        db.commit()
        from app.services.job_queue import cancel_pending_queue_job

        cancelled = cancel_pending_queue_job(db, job.id, now=now)
        claimed = claim_next_job(db, now=now, workspace_id=1)
        assert cancelled is True
        assert claimed is None
        db.refresh(job)
        assert job.status == "success"


def test_active_fingerprint_is_unique_under_concurrency() -> None:
    engine = _memory_engine()
    now = datetime.now(UTC)
    with Session(engine) as db:
        db.add(
            QueueJob(
                job_type="geo_opportunity.discover",
                status="pending",
                scheduled_at=now,
                payload_json={
                    "workspace_id": 1,
                    "company_id": 1,
                    "input_fingerprint": "same-scope",
                },
            )
        )
        db.commit()
        db.add(
            QueueJob(
                job_type="geo_opportunity.discover",
                status="pending",
                scheduled_at=now,
                payload_json={
                    "workspace_id": 1,
                    "company_id": 1,
                    "input_fingerprint": "same-scope",
                },
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_agent_workspace_root_uses_api_private_artifacts_in_container() -> None:
    assert agent_workspace_artifact_root(
        Path("/app/app/v1/agent_workspace.py")
    ) == Path("/app/private_artifacts/agent-workspace")


def test_request_draft_refuses_official_site_and_requires_draft_only(monkeypatch) -> None:
    from app.services.article_sync_adapter import StdioMcpArticleSyncAdapter

    adapter = StdioMcpArticleSyncAdapter(server_path="/unused/index.js", token="test")
    with pytest.raises(RuntimeError, match="official_site"):
        adapter.request_draft(
            platform_key="official_site",
            title="官网稿",
            body_markdown="不得走同步助手",
        )

    calls: list[dict] = []

    def fake_call(self, name: str, arguments: dict, *, timeout_seconds: float = 360.0) -> dict:
        calls.append(arguments)
        if name == "list_platforms":
            return {
                "content": [
                    {
                        "type": "text",
                        "text": '[{"id":"zhihu","name":"知乎","isAuthenticated":true}]',
                    }
                ]
            }
        return {
            "content": [
                {
                    "type": "text",
                    "text": '{"syncId":"s1","results":[{"platform":"zhihu","success":true,"draftOnly":false}]}',
                }
            ]
        }

    monkeypatch.setattr(StdioMcpArticleSyncAdapter, "_call_tool", fake_call)
    with pytest.raises(RuntimeError, match="draft"):
        adapter.request_draft(platform_key="zhihu", title="t", body_markdown="body")
    assert calls[-1].get("draftOnly") is True


def test_mcp_request_route_rejects_official_site(monkeypatch, issue27_api) -> None:
    from app.v1 import content_delivery_routes
    from app.models.cleanroom_v1 import GeoDistributionRun, GeoDistributionTarget

    client, sessions, ids = issue27_api
    with sessions() as db:
        db.add(
            GeoOptimizationAction(
                id=9,
                workspace_id=1,
                title="article",
                rationale="r",
                priority="high",
                status="in_progress",
                stage="executing",
                action_type="article",
            )
        )
        db.add(
            GeoDistributionRun(
                id=1,
                workspace_id=1,
                action_id=9,
                requested_platforms=["official_site"],
                stage="queued",
                idempotency_key="mcp-official",
                status="pending",
                requested_by_user_id=1,
            )
        )
        db.flush()
        db.add(
            GeoDistributionTarget(
                id=1,
                distribution_run_id=1,
                platform_variant_id=None,
                platform_key="official_site",
                adapter_version="mcp.v1",
                request_status="not_started",
                draft_readback_status="not_checked",
                human_publish_status="not_ready",
                publication_verification_status="not_checked",
                final_action_clicked=False,
            )
        )
        db.commit()

    monkeypatch.setattr(
        content_delivery_routes,
        "resolve_article_sync_credentials",
        lambda db, workspace_id: ("/unused", "token"),
    )

    class BoomAdapter:
        def request_draft(self, **kwargs):
            raise AssertionError("official_site must not reach MCP adapter")

    monkeypatch.setattr(content_delivery_routes, "get_article_sync_adapter", lambda **kwargs: BoomAdapter())
    response = client.post(
        f"/api/v1/workspaces/{ids['workspace_a']}/distribution-runs/1/request",
        headers=_auth(ids["token_a"]),
    )
    assert response.status_code in {409, 422}, response.text
    with sessions() as db:
        target = db.get(GeoDistributionTarget, 1)
        assert target is not None
        assert target.request_status != "mcp_request_accepted"


def test_completed_requires_comparable_retest() -> None:
    engine = _memory_engine()
    with Session(engine) as db:
        db.add(Company(id=1, name="Tenant A", brand_aliases=[]))
        db.add(GeoWorkspace(id=1, company_id=1, slug="a", brand_name="A", brand_aliases=[]))
        action = GeoOptimizationAction(
            id=1,
            workspace_id=1,
            title="article",
            rationale="r",
            priority="high",
            status="in_progress",
            stage="executing",
            action_type="article",
            workflow_version="action-flow.v2",
        )
        db.add(action)
        db.add(
            GeoActionTarget(
                id=1,
                workspace_id=1,
                action_id=1,
                target_key="zhihu",
                target_type="platform",
                platform_key="zhihu",
                display_name="知乎",
                target_ref="zhihu",
                delivery_status="publicly_verified",
                ordinal=0,
                metadata_json={},
            )
        )
        db.commit()
        assert derive_delivery_stage(db, action) == "ready_for_retest"
        db.add(
            GeoReobservation(
                action_id=1,
                workspace_id=1,
                round_index=1,
                status="completed",
                conclusion="improved",
            )
        )
        db.commit()
        assert derive_delivery_stage(db, action) == "completed"
