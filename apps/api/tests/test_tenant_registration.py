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


def test_legacy_user_provisioning_is_not_public(tenant_client: TestClient) -> None:
    response = tenant_client.post(
        "/api/auth/register",
        json={"name": "越权用户", "email": "blocked@example.com", "password": "a-safe-password-2026"},
    )
    assert response.status_code == 401
