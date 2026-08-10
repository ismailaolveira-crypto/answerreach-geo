from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.session import Base, get_db
from app.main import create_app


@pytest.fixture
def tenant_client() -> Generator[TestClient, None, None]:
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
    yield TestClient(app)
    app.dependency_overrides.clear()


def register(client: TestClient, *, email: str, company: str, brand: str) -> dict:
    response = client.post(
        "/api/auth/register-tenant",
        json={
            "name": "测试管理员",
            "email": email,
            "password": "a-safe-password-2026",
            "company_name": company,
            "brand_name": brand,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_registration_creates_a_private_company_workspace_and_login_token(
    tenant_client: TestClient,
) -> None:
    first = register(
        tenant_client,
        email="first@example.com",
        company="第一家公司",
        brand="第一品牌",
    )
    second = register(
        tenant_client,
        email="second@example.com",
        company="第二家公司",
        brand="第二品牌",
    )

    first_workspaces = tenant_client.get(
        "/api/v1/workspaces",
        headers={"Authorization": f"Bearer {first['access_token']}"},
    )
    assert first_workspaces.status_code == 200
    assert [item["id"] for item in first_workspaces.json()] == [first["workspace_id"]]
    assert first_workspaces.json()[0]["brand_name"] == "第一品牌"

    second_workspaces = tenant_client.get(
        "/api/v1/workspaces",
        headers={"Authorization": f"Bearer {second['access_token']}"},
    )
    assert second_workspaces.status_code == 200
    assert [item["id"] for item in second_workspaces.json()] == [second["workspace_id"]]

    denied = tenant_client.get(
        f"/api/v1/workspaces/{first['workspace_id']}/question-library",
        headers={"Authorization": f"Bearer {second['access_token']}"},
    )
    assert denied.status_code == 404

    login = tenant_client.post(
        "/api/auth/login",
        json={"email": "first@example.com", "password": "a-safe-password-2026"},
    )
    assert login.status_code == 200, login.text
    assert login.json()["user"]["email"] == "first@example.com"
    assert login.json()["access_token"]


def test_legacy_user_provisioning_is_not_public(tenant_client: TestClient) -> None:
    response = tenant_client.post(
        "/api/auth/register",
        json={"name": "越权用户", "email": "blocked@example.com", "password": "a-safe-password-2026"},
    )
    assert response.status_code == 401


def test_email_identity_is_case_insensitive_and_persisted_canonically(
    tenant_client: TestClient,
) -> None:
    created = register(
        tenant_client,
        email="Mixed.Case@Example.COM",
        company="大小写账号公司",
        brand="大小写品牌",
    )
    assert created["user"]["email"] == "mixed.case@example.com"

    login = tenant_client.post(
        "/api/auth/login",
        json={
            "email": "MIXED.CASE@EXAMPLE.COM",
            "password": "a-safe-password-2026",
        },
    )
    assert login.status_code == 200, login.text

    duplicate = tenant_client.post(
        "/api/auth/register-tenant",
        json={
            "name": "重复账号",
            "email": "mixed.case@example.com",
            "password": "another-safe-password-2026",
            "company_name": "不应创建的公司",
            "brand_name": "不应创建的品牌",
        },
    )
    assert duplicate.status_code == 409


def test_login_attempts_are_throttled_and_success_clears_failures(
    tenant_client: TestClient,
) -> None:
    register(
        tenant_client,
        email="throttle@example.com",
        company="登录节流公司",
        brand="登录节流品牌",
    )
    for _ in range(2):
        failed = tenant_client.post(
            "/api/auth/login",
            json={"email": "throttle@example.com", "password": "wrong-password"},
        )
        assert failed.status_code == 401
    success = tenant_client.post(
        "/api/auth/login",
        json={"email": "throttle@example.com", "password": "a-safe-password-2026"},
    )
    assert success.status_code == 200
    assert tenant_client.post(
        "/api/auth/login",
        json={"email": "throttle@example.com", "password": "wrong-password"},
    ).status_code == 401

    for _ in range(5):
        failed = tenant_client.post(
            "/api/auth/login",
            json={"email": "missing@example.com", "password": "wrong-password"},
        )
        assert failed.status_code == 401
    blocked = tenant_client.post(
        "/api/auth/login",
        json={"email": "missing@example.com", "password": "wrong-password"},
    )
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
