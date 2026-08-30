from collections.abc import Generator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.session import Base, get_db
from app.main import create_app
from app.models import (
    AuthSession,
    DeliveryPackageAccessLog,
    LLMProvider,
    PlacementRecord,
    Project,
    SystemAlert,
    User,
)
from app.models.cleanroom_v1 import GeoWorkspaceSecret
from app.services.auth import hash_password, issue_access_token
from scripts import init_production as init_production_script
from app.services.workspace_secrets import (
    ARTICLE_SYNC_MCP_SERVER_PATH,
    DEEPSEEK_API_KEY,
    get_workspace_secret,
    normalize_provider_auth_config,
)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def security_api() -> Generator[SimpleNamespace, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield SimpleNamespace(client=TestClient(app), sessions=session_factory)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _register(client: TestClient, email: str) -> dict:
    response = client.post(
        "/api/auth/register-tenant",
        json={
            "name": email.split("@", 1)[0],
            "email": email,
            "password": "a-safe-password-2026",
            "company_name": f"{email} company",
            "brand_name": f"{email} brand",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_workspace_secret_never_overwrites_the_global_provider(security_api: SimpleNamespace) -> None:
    first = _register(security_api.client, "first-tenant@example.com")
    second = _register(security_api.client, "second-tenant@example.com")
    original = normalize_provider_auth_config({"api_key": "platform-owned-key"})
    with security_api.sessions() as db:
        provider = LLMProvider(
            name="Platform DeepSeek",
            provider_type="deepseek_web_search",
            api_base_url="https://api.deepseek.com/anthropic",
            model_name="deepseek-v4-flash",
            auth_config=original,
            cost_rule={},
            status="active",
        )
        db.add(provider)
        db.commit()
        provider_id = provider.id

    response = security_api.client.patch(
        f"/api/v1/workspaces/{first['workspace_id']}/integrations",
        headers={"Authorization": f"Bearer {first['access_token']}"},
        json={"deepseek_api_key": "first-workspace-key"},
    )
    assert response.status_code == 200, response.text

    with security_api.sessions() as db:
        provider = db.get(LLMProvider, provider_id)
        assert provider is not None
        assert provider.auth_config == original
        assert get_workspace_secret(db, first["workspace_id"], DEEPSEEK_API_KEY) == (
            "first-workspace-key"
        )
        second_secret = db.scalar(
            select(GeoWorkspaceSecret).where(
                GeoWorkspaceSecret.workspace_id == second["workspace_id"],
                GeoWorkspaceSecret.secret_key == DEEPSEEK_API_KEY,
            )
        )
        assert second_secret is None


def test_workspace_manager_cannot_choose_an_executable_server_path(
    security_api: SimpleNamespace,
) -> None:
    tenant = _register(security_api.client, "operator-boundary@example.com")
    response = security_api.client.patch(
        f"/api/v1/workspaces/{tenant['workspace_id']}/integrations",
        headers=_auth(tenant["access_token"]),
        json={"article_sync_mcp_server_path": "/tmp/attacker-controlled.mjs"},
    )
    assert response.status_code == 200, response.text
    assert "article_sync_mcp_server_path" not in response.json()
    with security_api.sessions() as db:
        assert get_workspace_secret(
            db, tenant["workspace_id"], ARTICLE_SYNC_MCP_SERVER_PATH
        ) is None


@pytest.mark.parametrize(
    "suffix",
    ("operating-trends", "stage-goals", "stage-goals/1/timeline"),
)
def test_project_management_reads_require_authentication(
    security_api: SimpleNamespace, suffix: str
) -> None:
    response = security_api.client.get(f"/api/projects/999/{suffix}")
    assert response.status_code == 401


def test_request_id_is_stable_and_rejects_log_injection(
    security_api: SimpleNamespace,
) -> None:
    stable = security_api.client.get(
        "/api/health",
        headers={"X-Request-ID": "support-case-20260830"},
    )
    assert stable.headers["x-request-id"] == "support-case-20260830"
    unsafe = security_api.client.get(
        "/api/health",
        headers={"X-Request-ID": "bad forged-log-line"},
    )
    generated = unsafe.headers["x-request-id"]
    assert generated != "bad forged-log-line"
    assert len(generated) == 32


def test_public_delivery_requires_separate_confirmation_code_and_is_idempotent(
    security_api: SimpleNamespace,
) -> None:
    tenant = _register(security_api.client, "delivery-owner@example.com")
    with security_api.sessions() as db:
        owner = db.scalar(select(User).where(User.email == "delivery-owner@example.com"))
        assert owner is not None and owner.company_id is not None
        project = Project(company_id=owner.company_id, name="Secure delivery")
        db.add(project)
        db.flush()
        placement = PlacementRecord(
            project_id=project.id,
            channel="official-site",
            status="published",
            visibility="customer_visible",
            delivery_status="delivered",
        )
        db.add(placement)
        db.commit()
        project_id = project.id
        placement_id = placement.id

    created = security_api.client.post(
        f"/api/projects/{project_id}/delivery-shares",
        headers=_auth(tenant["access_token"]),
        json={"name": "External review"},
    )
    assert created.status_code == 201, created.text
    share = created.json()
    assert share["confirmation_token"]
    public_view = security_api.client.get(
        f"/api/public/delivery-packages/{share['token']}"
    )
    assert public_view.status_code == 200, public_view.text
    assert "confirmation_token" not in public_view.text

    wrong = security_api.client.post(
        f"/api/public/delivery-packages/{share['token']}/placements/{placement_id}/confirm",
        json={
            "confirmation_token": "x" * 24,
            "actor_name": "Reviewer",
        },
    )
    assert wrong.status_code == 403
    payload = {
        "confirmation_token": share["confirmation_token"],
        "actor_name": "Reviewer",
        "comment": "Accepted with evidence",
    }
    accepted = security_api.client.post(
        f"/api/public/delivery-packages/{share['token']}/placements/{placement_id}/confirm",
        json=payload,
    )
    assert accepted.status_code == 200, accepted.text
    replay = security_api.client.post(
        f"/api/public/delivery-packages/{share['token']}/placements/{placement_id}/confirm",
        json=payload,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == accepted.json()["id"]

    with security_api.sessions() as db:
        placement = db.get(PlacementRecord, placement_id)
        assert placement is not None and placement.delivery_status == "accepted"
        confirmations = list(
            db.scalars(
                select(DeliveryPackageAccessLog).where(
                    DeliveryPackageAccessLog.event_type == "confirm_report"
                )
            )
        )
        alerts = list(
            db.scalars(select(SystemAlert).where(SystemAlert.alert_type == "delivery.confirmed"))
        )
        assert len(confirmations) == 1
        assert len(alerts) == 1
        assert share["token"] not in str(confirmations[0].detail_json)
        assert share["token"] not in str(alerts[0].detail_json)


def test_provider_auth_config_encrypts_new_keys_and_preserves_existing_ciphertext() -> None:
    secured = normalize_provider_auth_config(
        {"api_key": "provider-secret", "region": "cn"}
    )
    assert "api_key" not in secured
    assert secured["api_key_encrypted"] != "provider-secret"
    assert secured["api_key_configured"] is True

    unchanged = normalize_provider_auth_config(
        {"api_key": "***configured***", "region": "sg"},
        existing=secured,
    )
    assert unchanged["api_key_encrypted"] == secured["api_key_encrypted"]
    assert unchanged["region"] == "sg"


def test_provider_api_never_persists_or_returns_plaintext_key(
    security_api: SimpleNamespace,
) -> None:
    with security_api.sessions() as db:
        admin = User(
            name="Provider Admin",
            email="provider-admin@example.com",
            password_hash=hash_password("provider-admin-password"),
            role="super_admin",
            status="active",
        )
        db.add(admin)
        db.flush()
        token = issue_access_token(db, admin)
        db.commit()

    response = security_api.client.post(
        "/api/llm-providers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Encrypted Provider",
            "provider_type": "openai_compatible",
            "api_base_url": "https://provider.example/v1",
            "model_name": "provider-model",
            "auth_config": {"api_key": "provider-api-secret"},
            "cost_rule": {},
            "status": "active",
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["auth_config"] == {"api_key_configured": True}
    with security_api.sessions() as db:
        provider = db.get(LLMProvider, payload["id"])
        assert provider is not None
        assert "api_key" not in provider.auth_config
        assert provider.auth_config["api_key_encrypted"] != "provider-api-secret"


def test_password_reset_revokes_all_existing_sessions(security_api: SimpleNamespace) -> None:
    with security_api.sessions() as db:
        admin = User(
            name="Security Admin",
            email="security-admin@example.com",
            password_hash=hash_password("admin-password-2026"),
            role="super_admin",
            status="active",
        )
        target = User(
            name="Target User",
            email="target-user@example.com",
            password_hash=hash_password("target-password-2026"),
            role="viewer",
            status="active",
        )
        db.add_all([admin, target])
        db.flush()
        admin_token = issue_access_token(db, admin)
        target_token = issue_access_token(db, target)
        db.commit()
        target_id = target.id

    reset = security_api.client.patch(
        f"/api/users/{target_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"password": "new-target-password-2026"},
    )
    assert reset.status_code == 200, reset.text
    revoked = security_api.client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {target_token}"},
    )
    assert revoked.status_code == 401
    assert revoked.json()["detail"] == "Session expired or revoked"


def test_production_admin_password_rotation_revokes_existing_sessions(
    security_api: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with security_api.sessions() as db:
        admin = User(
            name="Production Admin",
            email="production-admin@example.com",
            password_hash=hash_password("old-admin-password-2026"),
            role="super_admin",
            status="active",
        )
        db.add(admin)
        db.flush()
        issue_access_token(db, admin)
        db.commit()
        admin_id = admin.id
        original_version = admin.credentials_version

    monkeypatch.setattr(init_production_script, "SessionLocal", security_api.sessions)
    init_production_script.init_production(
        "production-admin@example.com", "new-admin-password-2026"
    )

    with security_api.sessions() as db:
        admin = db.get(User, admin_id)
        assert admin is not None
        assert admin.credentials_version == original_version + 1
        sessions = list(db.scalars(select(AuthSession).where(AuthSession.user_id == admin_id)))
        assert sessions
        assert all(session.revoked_at is not None for session in sessions)
