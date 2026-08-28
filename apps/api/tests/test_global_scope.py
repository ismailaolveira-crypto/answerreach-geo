from collections.abc import Generator
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.api.deps import get_current_user
from app.db.session import Base, get_db
from app.main import create_app
from app.models.company import Company
from app.models.cleanroom_v1 import (
    GeoObservationBatch,
    GeoObservationTask,
    GeoQuestionPlan,
    GeoWorkspace,
)
from app.models.user import User
from app.services.workspace_access import add_membership
from app.v1.global_scope import _resolve_dates, _scope_fingerprint


@pytest.fixture
def scope_client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        db.add(Company(id=1, name="范围测试企业"))
        db.add(
            User(
                id=1,
                company_id=1,
                name="范围管理员",
                email="scope@example.com",
                role="company_admin",
            )
        )
        db.add(
            GeoWorkspace(
                id=1,
                company_id=1,
                slug="scope-workspace",
                brand_name="春秋元泉",
                brand_aliases=[],
            )
        )
        db.add(
            GeoWorkspace(
                id=2,
                company_id=1,
                slug="hidden-scope-workspace",
                brand_name="不可访问",
                brand_aliases=[],
            )
        )
        for question_id, text in ((1, "企业如何选择 GEO 服务？"), (2, "GEO 如何衡量效果？")):
            db.add(
                GeoQuestionPlan(
                    id=question_id,
                    workspace_id=1,
                    question_text=text,
                    journey_stage="consideration",
                    role="business_owner",
                    topic_tags=[],
                    importance=6 - question_id,
                    is_brand_query=False,
                    active=True,
                    status="active",
                    source_type="manual",
                    source_evidence={},
                    template_variables=[],
                )
            )
        batch = GeoObservationBatch(
            id=11,
            workspace_id=1,
            source_type="official_api",
            status="completed",
            provider_count=2,
            question_count=2,
            repeat_count=1,
            total_tasks=2,
            completed_tasks=2,
            failed_tasks=0,
            configuration={},
            completed_at=datetime.now(timezone.utc),
        )
        db.add(batch)
        db.flush()
        for task_id, model_key, model_label, question_id in (
            (1, "deepseek", "DeepSeek", 1),
            (2, "qianwen", "通义千问", 2),
        ):
            db.add(
                GeoObservationTask(
                    id=task_id,
                    batch_id=11,
                    workspace_id=1,
                    provider_key=model_key,
                    provider_label=model_label,
                    model_key=model_key,
                    model_label=model_label,
                    question_plan_id=question_id,
                    question_text_snapshot="测试问题",
                    sample_key=f"scope-{task_id}",
                    repeat_index=1,
                    repeat_count=1,
                    status="success",
                    attempt_count=1,
                )
            )
        db.flush()
        add_membership(db, workspace_id=1, user_id=1, role="owner")
        db.commit()

    app = create_app()

    def override_db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1, company_id=1, role="company_admin"
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_scope_options_use_real_workspace_rows_and_stable_fingerprint(
    scope_client: TestClient,
) -> None:
    first = scope_client.get("/api/v1/workspaces/1/global-scope-options?range=30d")
    second = scope_client.get("/api/v1/workspaces/1/global-scope-options?range=30d")
    assert first.status_code == 200
    payload = first.json()
    assert payload["scope"]["batch_ids"] == [11]
    assert payload["scope"]["model_keys"] == ["deepseek", "qianwen"]
    assert payload["scope"]["question_plan_ids"] == [1, 2]
    assert payload["scope"]["fingerprint"] == second.json()["scope"]["fingerprint"]
    assert [item["id"] for item in payload["batches"]] == [11]
    assert {item["key"] for item in payload["models"]} == {"deepseek", "qianwen"}


def test_scope_options_remove_out_of_workspace_and_unavailable_selections(
    scope_client: TestClient,
) -> None:
    response = scope_client.get(
        "/api/v1/workspaces/1/global-scope-options"
        "?batch=11&batch=999&model=deepseek&model=unknown&question=1&question=999"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["scope"]["batch_ids"] == [11]
    assert payload["scope"]["model_keys"] == ["deepseek"]
    assert payload["scope"]["question_plan_ids"] == [1]
    assert len(payload["corrections"]) == 3


def test_scope_options_enforce_tenant_boundary(scope_client: TestClient) -> None:
    response = scope_client.get("/api/v1/workspaces/2/global-scope-options")
    assert response.status_code == 404


def test_custom_date_validation_and_canonical_hash_are_deterministic() -> None:
    preset, date_from, date_to, corrections = _resolve_dates(
        "custom", None, None, None
    )
    assert preset == "30d"
    assert date_to >= date_from
    assert corrections == ["自定义日期无效，已改为最近 30 天"]
    left = {"modelKeys": ["deepseek"], "batchIds": [11], "version": 1}
    right = {"version": 1, "batchIds": [11], "modelKeys": ["deepseek"]}
    assert _scope_fingerprint(left) == _scope_fingerprint(right)
