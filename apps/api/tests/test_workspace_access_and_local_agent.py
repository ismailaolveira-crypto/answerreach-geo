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
from app.models.cleanroom_v1 import GeoWorkspace
from app.models.user import User
from app.models.workspace_access import (
    LocalAgentEnrollment,
    LocalAgentNode,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from app.services.auth import create_access_token, hash_password
from app.services.workspace_access import add_membership, token_digest
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
        db.commit()
        ids = {
            "company": company.id,
            "other_company": other_company.id,
            "owner": owner.id,
            "non_member": same_company_non_member.id,
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


def headers(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def test_same_company_non_member_cannot_list_or_open_workspace(access_api) -> None:
    client, _session, ids = access_api
    response = client.get("/api/v1/workspaces", headers=headers(ids["non_member"]))
    assert response.status_code == 200
    assert response.json() == []
    denied = client.get(
        f"/api/v1/workspaces/{ids['workspace']}/members",
        headers=headers(ids["non_member"]),
    )
    assert denied.status_code == 404
    cannot_create = client.post(
        "/api/v1/workspaces",
        headers=headers(ids["non_member"]),
        json={
            "company_id": ids["company"],
            "slug": "must-not-create",
            "brand_name": "Must Not Create",
            "brand_aliases": [],
            "status": "active",
        },
    )
    assert cannot_create.status_code == 403


def test_invitation_creates_member_once_and_stores_only_token_hash(access_api) -> None:
    client, testing_session, ids = access_api
    created = client.post(
        f"/api/v1/workspaces/{ids['workspace']}/invitations",
        headers=headers(ids["owner"]),
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
        headers=headers(ids["owner"]),
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
        headers=headers(ids["owner"]),
    )
    assert response.status_code == 409


def test_local_agent_enrollment_heartbeat_and_secret_rejection(access_api) -> None:
    client, testing_session, ids = access_api
    enrollment = client.post(
        f"/api/v1/workspaces/{ids['workspace']}/local-agent-enrollments",
        headers=headers(ids["owner"]),
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


def test_provider_output_path_is_resolvable_without_fixed_parent_depth() -> None:
    assert _project_output_root().name == "outputs"
