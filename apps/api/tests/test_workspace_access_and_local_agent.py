from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base, get_db
from app.core.config import Settings
from app.main import app
from app.models.company import Company
from app.models.cleanroom_v1 import (
    GeoObservationBatch,
    GeoObservationTask,
    GeoQuestionPlan,
    GeoWorkspace,
)
from app.models.audit import AuditLog
from app.models.job import QueueJob
from app.models.search import LLMProvider, LLMProviderTestRun
from app.models.user import User
from app.models.workspace_access import (
    LocalAgentEnrollment,
    LocalAgentNode,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from app.services.auth import hash_password, issue_access_token
from app.services.workspace_access import add_membership, token_digest
from app.services.worker_heartbeat import register_worker
from app.services.worker_service import (
    ManagedWorkerRepairResult,
    ManagedWorkerServiceStatus,
)
from app.api.routes.providers import _project_output_root


@pytest.fixture()
def access_api() -> Generator[tuple[TestClient, sessionmaker[Session], dict], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with testing_session() as db:
        company = Company(name="LAN Team", status="active", brand_aliases=[])
        other_company = Company(name="Other Team", status="active", brand_aliases=[])
        db.add_all([company, other_company])
        db.flush()
        owner = User(
            company_id=company.id,
            name="Owner",
            email="owner@example.com",
            password_hash=hash_password("owner-password"),
            role="company_admin",
            status="active",
        )
        same_company_non_member = User(
            company_id=company.id,
            name="No Access",
            email="no-access@example.com",
            password_hash=hash_password("no-access-password"),
            role="content_operator",
            status="active",
        )
        db.add_all([owner, same_company_non_member])
        db.flush()
        workspace = GeoWorkspace(
            company_id=company.id,
            slug="lan-team",
            brand_name="LAN Brand",
            brand_aliases=[],
            status="active",
        )
        hidden_workspace = GeoWorkspace(
            company_id=company.id,
            slug="hidden-team",
            brand_name="Hidden Brand",
            brand_aliases=[],
            status="active",
        )
        db.add_all([workspace, hidden_workspace])
        db.flush()
        owner_membership = add_membership(
            db, workspace_id=workspace.id, user_id=owner.id, role="owner"
        )
        # Establish explicit membership mode on the second workspace too.
        add_membership(db, workspace_id=hidden_workspace.id, user_id=owner.id, role="owner")
        owner_token = issue_access_token(db, owner)
        non_member_token = issue_access_token(db, same_company_non_member)
        db.commit()
        ids = {
            "company": company.id,
            "other_company": other_company.id,
            "owner": owner.id,
            "owner_token": owner_token,
            "non_member": same_company_non_member.id,
            "non_member_token": non_member_token,
            "workspace": workspace.id,
            "hidden_workspace": hidden_workspace.id,
            "owner_membership": owner_membership.id,
        }

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app), testing_session, ids
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_same_company_non_member_cannot_list_or_open_workspace(access_api) -> None:
    client, _session, ids = access_api
    response = client.get("/api/v1/workspaces", headers=headers(ids["non_member_token"]))
    assert response.status_code == 200
    assert response.json() == []
    denied = client.get(
        f"/api/v1/workspaces/{ids['workspace']}/members",
        headers=headers(ids["non_member_token"]),
    )
    assert denied.status_code == 404
    cannot_create = client.post(
        "/api/v1/workspaces",
        headers=headers(ids["non_member_token"]),
        json={
            "company_id": ids["company"],
            "slug": "must-not-create",
            "brand_name": "Must Not Create",
            "brand_aliases": [],
            "status": "active",
        },
    )
    assert cannot_create.status_code == 403


def test_empty_workspace_never_falls_back_to_company_wide_access(access_api) -> None:
    client, testing_session, ids = access_api
    with testing_session() as db:
        empty_workspace = GeoWorkspace(
            company_id=ids["company"],
            slug="empty-membership-boundary",
            brand_name="Empty Membership Boundary",
            brand_aliases=[],
            status="active",
        )
        db.add(empty_workspace)
        db.commit()
        workspace_id = empty_workspace.id

    listed = client.get("/api/v1/workspaces", headers=headers(ids["non_member_token"]))
    assert listed.status_code == 200
    assert all(item["id"] != workspace_id for item in listed.json())
    denied = client.get(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=headers(ids["non_member_token"]),
    )
    assert denied.status_code == 404


def test_queue_worker_status_is_live_and_workspace_protected(access_api) -> None:
    client, testing_session, ids = access_api
    now = datetime.now(UTC)
    with testing_session() as db:
        register_worker(
            db,
            worker_id="queue:test:route",
            mode="continuous",
            hostname="route-test",
            process_id=303,
            concurrency=8,
            workspace_id=None,
            observation_batch_id=None,
            now=now,
        )
        db.add(
            QueueJob(
                job_type="geo_observation.collect",
                status="pending",
                scheduled_at=now,
                payload_json={
                    "workspace_id": ids["workspace"],
                    "dispatch_enabled": True,
                },
            )
        )
        db.commit()

    response = client.get(
        f"/api/v1/workspaces/{ids['workspace']}/queue-worker-status",
        headers=headers(ids["owner_token"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["online"] is True
    assert response.json()["concurrency"] == 8
    assert response.json()["pending_jobs"] == 1
    assert response.json()["historical_jobs"] == 0

    denied = client.get(
        f"/api/v1/workspaces/{ids['workspace']}/queue-worker-status",
        headers=headers(ids["non_member_token"]),
    )
    assert denied.status_code == 404


def test_queue_worker_repair_requires_manager_and_records_result(
    access_api, monkeypatch
) -> None:
    client, testing_session, ids = access_api
    now = datetime.now(UTC)
    with testing_session() as db:
        register_worker(
            db,
            worker_id="managed:test-route",
            mode="continuous",
            hostname="route-test",
            process_id=606,
            concurrency=8,
            workspace_id=None,
            observation_batch_id=None,
            now=now,
        )

    service_status = ManagedWorkerServiceStatus(
        supported=True,
        installed=True,
        running=True,
        repository_match=True,
        state="running",
        pid=606,
        label="com.chunqiu-yuanquan.geo.worker",
        message="Worker 已由系统守护。",
    )
    monkeypatch.setattr(
        "app.v1.routes.repair_managed_worker_service",
        lambda: ManagedWorkerRepairResult(
            attempted=True,
            action="restarted",
            status=service_status,
            message="Worker 常驻服务已重新拉起。",
        ),
    )
    monkeypatch.setattr(
        "app.v1.routes.process_observation_schedules",
        lambda _db, workspace_id: {
            "checked_at": now.isoformat(),
            "dispatched": 0,
            "failed": 0,
            "deduplicated": 0,
        },
    )
    monkeypatch.setattr(
        "app.v1.routes.retry_worker_interrupted_schedule_runs",
        lambda _db, workspace_id, actor: {
            "checked_at": now.isoformat(),
            "retried": 1,
            "failed": 0,
            "skipped_scope_changed": 0,
        },
    )

    response = client.post(
        f"/api/v1/workspaces/{ids['workspace']}/queue-worker-repair",
        headers=headers(ids["owner_token"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "online"
    assert response.json()["service_action"] == "restarted"
    assert response.json()["schedule_retries"] == 1

    denied = client.post(
        f"/api/v1/workspaces/{ids['workspace']}/queue-worker-repair",
        headers=headers(ids["non_member_token"]),
    )
    assert denied.status_code == 404

    with testing_session() as db:
        audit = db.scalar(
            select(AuditLog).where(AuditLog.action == "queue_worker.repair")
        )
        assert audit is not None
        assert audit.resource_id == ids["workspace"]
        assert audit.detail_json["action"] == "restarted"


def test_offline_worker_rejects_batch_before_any_rows_are_created(access_api) -> None:
    client, testing_session, ids = access_api
    with testing_session() as db:
        before = (
            db.query(GeoObservationBatch).count(),
            db.query(GeoObservationTask).count(),
            db.query(QueueJob).count(),
        )

    response = client.post(
        f"/api/v1/workspaces/{ids['workspace']}/observation-batches",
        headers=headers(ids["owner_token"]),
        json={"provider_ids": [999], "question_plan_ids": [999], "repeat_count": 1},
    )

    assert response.status_code == 503, response.text
    assert "尚未创建" in response.json()["detail"]
    with testing_session() as db:
        after = (
            db.query(GeoObservationBatch).count(),
            db.query(GeoObservationTask).count(),
            db.query(QueueJob).count(),
        )
    assert after == before


def test_global_worker_accepts_truthful_pending_batches_for_two_accounts_and_workspaces(
    access_api,
) -> None:
    client, testing_session, ids = access_api
    now = datetime.now(UTC)
    with testing_session() as db:
        add_membership(
            db,
            workspace_id=ids["hidden_workspace"],
            user_id=ids["non_member"],
            role="operator",
            invited_by_user_id=ids["owner"],
        )
        questions = [
            GeoQuestionPlan(
                workspace_id=workspace_id,
                question_text=f"工作区 {workspace_id} 企业级大模型治理平台怎么选？",
                journey_stage="consideration",
                role="technical_lead",
                topic_tags=[],
                importance=5,
                is_brand_query=False,
                active=True,
                status="active",
                source_type="manual",
                source_evidence={},
                template_variables=[],
            )
            for workspace_id in (ids["workspace"], ids["hidden_workspace"])
        ]
        provider = LLMProvider(
            name="Test Qwen Search",
            provider_type="bailian_qwen_responses",
            api_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_name="qwen-plus",
            auth_config={"api_key": "fixture-not-a-real-key"},
            cost_rule={"platform_key": "qianwen"},
            status="active",
        )
        db.add_all([*questions, provider])
        db.commit()
        provider_id = provider.id
        question_ids = [question.id for question in questions]
        db.add(
            LLMProviderTestRun(
                provider_id=provider_id,
                actor_user_id=ids["owner"],
                ok=True,
                prompt_text="test-only readiness",
                answer_summary="test-only",
                latency_ms=1,
            )
        )
        db.commit()
        register_worker(
            db,
            worker_id="queue:test:all-workspaces",
            mode="continuous",
            hostname="route-test",
            process_id=404,
            concurrency=8,
            workspace_id=None,
            observation_batch_id=None,
            now=now,
        )

    first = client.post(
        f"/api/v1/workspaces/{ids['workspace']}/observation-batches",
        headers=headers(ids["owner_token"]),
        json={"provider_ids": [provider_id], "question_plan_ids": [question_ids[0]], "repeat_count": 1},
    )
    second = client.post(
        f"/api/v1/workspaces/{ids['hidden_workspace']}/observation-batches",
        headers=headers(ids["non_member_token"]),
        json={"provider_ids": [provider_id], "question_plan_ids": [question_ids[1]], "repeat_count": 1},
    )

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert first.json()["status"] == "pending"
    assert second.json()["status"] == "pending"
    assert first.json()["started_at"] is None
    assert second.json()["started_at"] is None
    with testing_session() as db:
        batches = list(db.scalars(select(GeoObservationBatch).order_by(GeoObservationBatch.id)))
        assert [batch.workspace_id for batch in batches] == [
            ids["workspace"],
            ids["hidden_workspace"],
        ]
        assert {batch.status for batch in batches} == {"pending"}
        receipts = list(
            db.scalars(
                select(QueueJob)
                .where(QueueJob.job_type == "geo_observation.batch")
                .order_by(QueueJob.id)
            )
        )
        assert [receipt.status for receipt in receipts] == ["queued", "queued"]
        assert all(receipt.payload_json["dispatch_enabled"] is True for receipt in receipts)
        children = list(
            db.scalars(
                select(QueueJob).where(QueueJob.job_type == "geo_observation.collect")
            )
        )
        assert len(children) == 2
        assert all(child.payload_json["dispatch_enabled"] is True for child in children)
        assert all(
            child.payload_json["dispatch_source"] == "current_page_submission"
            for child in children
        )


def test_observation_batch_capacity_blocks_repeated_queue_expansion(
    access_api,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, testing_session, ids = access_api
    monkeypatch.setattr(
        "app.v1.routes.get_settings",
        lambda: Settings(
            _env_file=None,
            observation_active_batch_limit=1,
            observation_pending_task_limit=10_000,
            observation_daily_task_limit=25_000,
            observation_batch_rate_limit_per_hour=10,
        ),
    )
    now = datetime.now(UTC)
    with testing_session() as db:
        question = GeoQuestionPlan(
            workspace_id=ids["workspace"],
            question_text="企业级大模型治理平台怎么选？",
            journey_stage="consideration",
            role="technical_lead",
            topic_tags=[],
            importance=5,
            is_brand_query=False,
            active=True,
            status="active",
            source_type="manual",
            source_evidence={},
            template_variables=[],
        )
        provider = LLMProvider(
            name="Capacity Test Search",
            provider_type="bailian_qwen_responses",
            api_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_name="qwen-plus",
            auth_config={"api_key": "fixture-not-a-real-key"},
            cost_rule={"platform_key": "qianwen"},
            status="active",
        )
        db.add_all([question, provider])
        db.flush()
        db.add(
            LLMProviderTestRun(
                provider_id=provider.id,
                actor_user_id=ids["owner"],
                ok=True,
                prompt_text="test-only readiness",
                answer_summary="test-only",
                latency_ms=1,
            )
        )
        register_worker(
            db,
            worker_id="queue:test:capacity",
            mode="continuous",
            hostname="route-test",
            process_id=405,
            concurrency=8,
            workspace_id=None,
            observation_batch_id=None,
            now=now,
        )
        db.commit()
        provider_id = provider.id
        question_id = question.id

    payload = {
        "provider_ids": [provider_id],
        "question_plan_ids": [question_id],
        "repeat_count": 1,
    }
    first = client.post(
        f"/api/v1/workspaces/{ids['workspace']}/observation-batches",
        headers=headers(ids["owner_token"]),
        json=payload,
    )
    blocked = client.post(
        f"/api/v1/workspaces/{ids['workspace']}/observation-batches",
        headers=headers(ids["owner_token"]),
        json=payload,
    )
    assert first.status_code == 202, first.text
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "当前运行中的观测批次已达到上限"
    listed = client.get(
        f"/api/v1/workspaces/{ids['workspace']}/observation-batches?page=1&page_size=100",
        headers=headers(ids["owner_token"]),
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["pagination"]["total"] == 1
    assert listed.json()["items"][0]["pending"] == 1
    with testing_session() as db:
        assert db.query(GeoObservationBatch).count() == 1
        assert db.query(GeoObservationTask).count() == 1


def test_invitation_creates_member_once_and_stores_only_token_hash(access_api) -> None:
    client, testing_session, ids = access_api
    created = client.post(
        f"/api/v1/workspaces/{ids['workspace']}/invitations",
        headers=headers(ids["owner_token"]),
        json={"email": "invitee@example.com", "role": "reviewer", "expires_in_hours": 24},
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["invite_path"].endswith(payload["invite_token"])
    with testing_session() as db:
        invitation = db.get(WorkspaceInvitation, payload["id"])
        assert invitation is not None
        assert invitation.token_hash == token_digest(payload["invite_token"])
        assert invitation.token_hash != payload["invite_token"]

    preview = client.get(f"/api/auth/invitations/{payload['invite_token']}")
    assert preview.status_code == 200
    assert preview.json()["workspace_name"] == "LAN Brand"
    accepted = client.post(
        "/api/auth/invitations/accept",
        json={
            "token": payload["invite_token"],
            "name": "Invitee",
            "password": "invitee-password",
        },
    )
    assert accepted.status_code == 200, accepted.text
    accepted_payload = accepted.json()
    assert accepted_payload["workspace_id"] == ids["workspace"]
    joined_headers = {"Authorization": f"Bearer {accepted_payload['access_token']}"}
    workspaces = client.get("/api/v1/workspaces", headers=joined_headers).json()
    assert [item["id"] for item in workspaces] == [ids["workspace"]]
    with testing_session() as db:
        invited_user = db.scalar(select(User).where(User.email == "invitee@example.com"))
        assert invited_user is not None
        assert invited_user.company_id is None
        assert invited_user.role == "viewer"
        invited_membership = db.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == ids["workspace"],
                WorkspaceMembership.user_id == invited_user.id,
            )
        )
        assert invited_membership is not None
        invited_membership_id = invited_membership.id

    revoked = client.delete(
        f"/api/v1/workspaces/{ids['workspace']}/members/{invited_membership_id}",
        headers=headers(ids["owner_token"]),
    )
    assert revoked.status_code == 200
    assert client.get("/api/v1/workspaces", headers=joined_headers).json() == []
    replay = client.post(
        "/api/auth/invitations/accept",
        json={
            "token": payload["invite_token"],
            "name": "Invitee",
            "password": "invitee-password",
        },
    )
    assert replay.status_code == 409


def test_expired_invitation_is_rejected(access_api) -> None:
    client, testing_session, ids = access_api
    created = client.post(
        f"/api/v1/workspaces/{ids['workspace']}/invitations",
        headers=headers(ids["owner_token"]),
        json={"email": "late@example.com", "role": "viewer", "expires_in_hours": 1},
    ).json()
    with testing_session() as db:
        invitation = db.get(WorkspaceInvitation, created["id"])
        assert invitation is not None
        invitation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    response = client.get(f"/api/auth/invitations/{created['invite_token']}")
    assert response.status_code == 410


def test_last_owner_cannot_be_removed(access_api) -> None:
    client, _session, ids = access_api
    response = client.delete(
        f"/api/v1/workspaces/{ids['workspace']}/members/{ids['owner_membership']}",
        headers=headers(ids["owner_token"]),
    )
    assert response.status_code == 409


def test_admin_cannot_promote_ownership_or_modify_an_owner(access_api) -> None:
    client, testing_session, ids = access_api
    with testing_session() as db:
        admin = User(
            company_id=ids["company"],
            name="Workspace Admin",
            email="workspace-admin@example.com",
            password_hash=hash_password("workspace-admin-password"),
            role="content_operator",
            status="active",
        )
        db.add(admin)
        db.flush()
        admin_membership = add_membership(
            db,
            workspace_id=ids["workspace"],
            user_id=admin.id,
            role="admin",
            invited_by_user_id=ids["owner"],
        )
        admin_token = issue_access_token(db, admin)
        db.commit()
        admin_membership_id = admin_membership.id

    promote_self = client.patch(
        f"/api/v1/workspaces/{ids['workspace']}/members/{admin_membership_id}",
        headers=headers(admin_token),
        json={"role": "owner"},
    )
    assert promote_self.status_code == 403

    demote_owner = client.patch(
        f"/api/v1/workspaces/{ids['workspace']}/members/{ids['owner_membership']}",
        headers=headers(admin_token),
        json={"role": "admin"},
    )
    assert demote_owner.status_code == 403

    revoke_owner = client.delete(
        f"/api/v1/workspaces/{ids['workspace']}/members/{ids['owner_membership']}",
        headers=headers(admin_token),
    )
    assert revoke_owner.status_code == 403


def test_local_agent_enrollment_heartbeat_and_secret_rejection(access_api) -> None:
    client, testing_session, ids = access_api
    enrollment = client.post(
        f"/api/v1/workspaces/{ids['workspace']}/local-agent-enrollments",
        headers=headers(ids["owner_token"]),
    )
    assert enrollment.status_code == 201, enrollment.text
    enrollment_payload = enrollment.json()
    assert "--server http://HOST:3000" in enrollment_payload["command_hint"]
    enrolled = client.post(
        "/api/v1/local-agent/enroll",
        json={
            "enrollment_token": enrollment_payload["enrollment_token"],
            "name": "Owner Mac",
            "hostname": "owner-mac.local",
            "platform": "macOS",
            "agent_version": "0.1.0",
            "capabilities": {
                "execution_mode": "status_only",
                "remote_job_execution": False,
                "egolite": {"installed": True},
            },
            "health": {"egolite": {"running": True, "login_state_inspected": False}},
        },
    )
    assert enrolled.status_code == 201, enrolled.text
    node_payload = enrolled.json()
    assert node_payload["execution_mode"] == "status_only"
    with testing_session() as db:
        node = db.get(LocalAgentNode, node_payload["id"])
        assert node is not None
        assert node.device_token_hash == token_digest(node_payload["device_token"])
        assert node.device_token_hash != node_payload["device_token"]
        enrollment_row = db.scalar(select(LocalAgentEnrollment))
        assert enrollment_row is not None and enrollment_row.used_at is not None

    replay = client.post(
        "/api/v1/local-agent/enroll",
        json={
            "enrollment_token": enrollment_payload["enrollment_token"],
            "name": "Replay",
            "hostname": "replay",
            "platform": "macOS",
            "agent_version": "0.1.0",
        },
    )
    assert replay.status_code == 409
    heartbeat = client.post(
        f"/api/v1/local-agent/nodes/{node_payload['id']}/heartbeat",
        headers={"X-Geo-Agent-Token": node_payload["device_token"]},
        json={
            "agent_version": "0.1.0",
            "capabilities": {"remote_job_execution": False},
            "health": {"egolite": {"running": False}},
        },
    )
    assert heartbeat.status_code == 200, heartbeat.text
    assert heartbeat.json()["online"] is True
    forbidden = client.post(
        f"/api/v1/local-agent/nodes/{node_payload['id']}/heartbeat",
        headers={"X-Geo-Agent-Token": node_payload["device_token"]},
        json={
            "agent_version": "0.1.0",
            "capabilities": {"cookie": "must-not-upload"},
            "health": {},
        },
    )
    assert forbidden.status_code == 422
    disguised_token = client.post(
        f"/api/v1/local-agent/nodes/{node_payload['id']}/heartbeat",
        headers={"X-Geo-Agent-Token": node_payload["device_token"]},
        json={
            "agent_version": "0.1.0",
            "capabilities": {"access_token": "must-not-upload"},
            "health": {},
        },
    )
    assert disguised_token.status_code == 422


def test_deployment_mode_rejects_lan_sqlite_and_default_secret() -> None:
    with pytest.raises(RuntimeError, match="requires PostgreSQL"):
        Settings(
            _env_file=None,
            deployment_mode="lan",
            database_url="sqlite:///local.db",
            auth_secret="unique-secret",
        ).validate_deployment()
    with pytest.raises(RuntimeError, match="unique AUTH_SECRET"):
        Settings(
            _env_file=None,
            deployment_mode="lan",
            database_url="postgresql+psycopg://user:pass@db/geo",
            auth_secret="dev-secret-change-me",
        ).validate_deployment()
    Settings(
        _env_file=None,
        deployment_mode="personal",
        database_url="sqlite:///local.db",
    ).validate_deployment()


def test_production_mode_requires_postgres_https_and_explicit_hosts() -> None:
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        Settings(
            _env_file=None,
            environment="production",
            deployment_mode="personal",
            database_url="sqlite:///local.db",
            auto_create_tables=False,
            auth_secret="x" * 32,
            internal_proxy_secret="p" * 32,
            cors_origins="https://geo.example.com",
            allowed_hosts="api.example.com",
        ).validate_deployment()
    with pytest.raises(RuntimeError, match="HTTPS"):
        Settings(
            _env_file=None,
            environment="production",
            deployment_mode="lan",
            database_url="postgresql+psycopg://user:pass@db/geo",
            auto_create_tables=False,
            auth_secret="x" * 32,
            internal_proxy_secret="p" * 32,
            cors_origins="http://geo.example.com",
            allowed_hosts="api.example.com",
            public_registration_enabled=False,
        ).validate_deployment()
    Settings(
        _env_file=None,
        environment="production",
        deployment_mode="lan",
        database_url="postgresql+psycopg://user:pass@db/geo",
        auto_create_tables=False,
        auth_secret="x" * 32,
        internal_proxy_secret="p" * 32,
        cors_origins="https://geo.example.com",
        allowed_hosts="api.example.com",
        public_registration_enabled=False,
    ).validate_deployment()
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        Settings(
            _env_file=None,
            environment=" production ",
            deployment_mode="personal",
            database_url="sqlite:///local.db",
            auto_create_tables=False,
            auth_secret="x" * 32,
            internal_proxy_secret="p" * 32,
            cors_origins="https://geo.example.com",
            allowed_hosts="api.example.com",
        ).validate_deployment()


def test_lan_and_production_reject_public_registration() -> None:
    with pytest.raises(RuntimeError, match="PUBLIC_REGISTRATION_ENABLED=false"):
        Settings(
            _env_file=None,
            deployment_mode="lan",
            database_url="postgresql+psycopg://user:pass@db/geo",
            auth_secret="x" * 32,
            internal_proxy_secret="p" * 32,
            public_registration_enabled=True,
        ).validate_deployment()


def test_railway_postgres_url_uses_installed_psycopg_driver() -> None:
    assert Settings(
        _env_file=None,
        database_url="postgresql://user:pass@postgres.internal:5432/railway",
    ).database_url == "postgresql+psycopg://user:pass@postgres.internal:5432/railway"
    assert Settings(
        _env_file=None,
        database_url="postgres://user:pass@postgres.internal:5432/railway",
    ).database_url == "postgresql+psycopg://user:pass@postgres.internal:5432/railway"


def test_provider_output_path_is_resolvable_without_fixed_parent_depth() -> None:
    assert _project_output_root().name == "outputs"
