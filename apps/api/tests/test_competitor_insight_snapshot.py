from collections.abc import Generator
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.api.deps import get_current_user
from app.db.session import Base, get_db
from app.main import create_app
from app.models.company import Company
from app.models.cleanroom_v1 import (
    GeoCompetitorInsightSnapshot,
    GeoEvidence,
    GeoObservationRun,
    GeoQuestionPlan,
    GeoWorkspace,
)
from app.models.user import User
from app.v1 import routes


def _evidence(evidence_id: int, answer: str) -> GeoEvidence:
    return GeoEvidence(
        id=evidence_id,
        workspace_id=1,
        run_id=1,
        question_plan_id=1,
        model_key="deepseek",
        model_label="DeepSeek",
        prompt_version="v1",
        sample_mode="api_web_search",
        evidence_level="auditable",
        collection_method="official_api_web_search",
        evidence_kind="provider_web_search",
        is_real_provider_evidence=True,
        brand_status="shortlisted" if "春秋元泉" in answer else "absent",
        competitor_positions=[],
        answer_text=answer,
        answer_hash=f"{evidence_id:064x}",
        source_items=[{"url": f"https://example.com/{evidence_id}"}],
        sampling_environment={"search_verified": True},
        raw_artifact_uri=f"file:///private/{evidence_id}.json",
        captured_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def competitor_report_api(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[SimpleNamespace, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    with session_factory() as db:
        db.add(Company(id=1, name="测试公司"))
        db.add_all(
            [
                User(
                    id=1,
                    company_id=1,
                    name="分析员一",
                    email="analyst1@example.com",
                    role="company_admin",
                ),
                User(
                    id=2,
                    company_id=1,
                    name="分析员二",
                    email="analyst2@example.com",
                    role="company_admin",
                ),
            ]
        )
        db.add(
            GeoWorkspace(
                id=1,
                company_id=1,
                slug="competitor-report",
                brand_name="春秋元泉",
                brand_aliases=["智能永信"],
                website_url="https://example.com",
            )
        )
        db.add(
            GeoQuestionPlan(
                id=1,
                workspace_id=1,
                question_text="Token 统一管控平台哪家好？",
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
        )
        db.add(
            GeoObservationRun(
                id=1,
                workspace_id=1,
                adapter_key="official_api_web_search",
                status="completed",
                request_context={},
                started_at=now,
                completed_at=now,
            )
        )
        db.add(_evidence(1, "推荐春秋元泉用于企业 Token 统一管控。"))
        db.commit()

    def fake_generate(_comparison: dict, **_kwargs: object) -> dict:
        return {
            "provider": "DeepSeek",
            "model": "deepseek-chat",
            "generated_at": datetime.now(timezone.utc),
            "scope": {
                "kind": "全部问题",
                "period": "近 90 天",
                "model": "全部已测模型",
                "question": "全部已选问题",
                "answer_count": 1,
                "real_provider_evidence_only": True,
            },
            "analysis": {
                "scope_summary": "当前范围有 1 条真实回答。",
                "overall_assessment": "当前证据显示品牌已被提及。",
                "findings": [
                    {
                        "title": "已有品牌信号",
                        "detail": "原回答可复核品牌提及。",
                        "evidence_ids": [1],
                    }
                ],
                "recommended_actions": ["继续补充可引用的公开材料。"],
                "limitations": ["样本量较小。"],
            },
        }

    monkeypatch.setattr(routes, "generate_competitor_insight", fake_generate)
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        with session_factory() as db:
            yield db

    identity = SimpleNamespace(
        value=SimpleNamespace(id=1, company_id=1, role="company_admin")
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: identity.value
    client = TestClient(app)
    yield SimpleNamespace(
        client=client,
        session_factory=session_factory,
        identity=identity,
    )
    client.close()
    app.dependency_overrides.clear()


def test_generated_report_is_persisted_without_changing_observation_evidence(
    competitor_report_api: SimpleNamespace,
) -> None:
    client: TestClient = competitor_report_api.client
    empty = client.get("/api/v1/workspaces/1/competitor-insights?period_days=90")
    assert empty.status_code == 200
    assert empty.json() is None

    created = client.post(
        "/api/v1/workspaces/1/competitor-insights",
        json={"period_days": 90, "model_key": "all"},
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["persisted"] is True
    assert payload["is_stale"] is False
    assert payload["snapshot_id"] == 1
    assert payload["source_evidence_count"] == 1

    restored = client.get("/api/v1/workspaces/1/competitor-insights?period_days=90")
    assert restored.status_code == 200
    assert restored.json()["snapshot_id"] == payload["snapshot_id"]
    assert restored.json()["analysis"] == payload["analysis"]

    with competitor_report_api.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(GeoEvidence)) == 1
        row = db.scalar(select(GeoCompetitorInsightSnapshot))
        assert row is not None
        assert row.created_by_user_id == 1
        assert row.source_evidence_ids == [1]
        assert row.linked_evidence_ids == [1]


def test_report_restore_is_account_scoped_and_marks_changed_inputs_stale(
    competitor_report_api: SimpleNamespace,
) -> None:
    client: TestClient = competitor_report_api.client
    assert client.post(
        "/api/v1/workspaces/1/competitor-insights",
        json={"period_days": 90},
    ).status_code == 200

    competitor_report_api.identity.value = SimpleNamespace(
        id=2, company_id=1, role="company_admin"
    )
    isolated = client.get("/api/v1/workspaces/1/competitor-insights?period_days=90")
    assert isolated.status_code == 200
    assert isolated.json() is None

    competitor_report_api.identity.value = SimpleNamespace(
        id=1, company_id=1, role="company_admin"
    )
    with competitor_report_api.session_factory() as db:
        db.add(_evidence(2, "阿里云 AI网关也进入候选，但未提及春秋元泉。"))
        db.commit()
    changed = client.get("/api/v1/workspaces/1/competitor-insights?period_days=90")
    assert changed.status_code == 200
    assert changed.json()["snapshot_id"] == 1
    assert changed.json()["is_stale"] is True
