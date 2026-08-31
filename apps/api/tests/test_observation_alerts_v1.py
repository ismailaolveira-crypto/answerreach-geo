from datetime import UTC, datetime
from collections.abc import Generator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.api.deps import get_current_user
from app.db.session import Base, get_db
from app.main import create_app
from app.models.company import Company
from app.models.cleanroom_v1 import (
    GeoChangeAlert,
    GeoEvidence,
    GeoObservationBatch,
    GeoObservationRun,
    GeoObservationSchedule,
    GeoObservationScheduleRun,
    GeoObservationTask,
    GeoQuestionPlan,
    GeoWorkspace,
)
from app.v1.observation_alerts import (
    canonical_fingerprint,
    evaluate_change_alerts,
    next_schedule_time,
    schedule_scope,
)
from app.models.search import LLMProvider
from app.models.user import User
from app.services.workspace_access import add_membership
from app.v1.observation_alert_routes import retry_worker_interrupted_schedule_runs


def add_batch(db: Session, batch_id: int, *, statuses: list[str], complete: bool = True) -> GeoObservationBatch:
    now = datetime.now(UTC)
    providers = [{"id": 1, "key": "deepseek", "model_name": "deepseek-chat"}]
    questions = [{"id": 1, "label": "哪家 GEO 平台值得选？"}]
    batch = GeoObservationBatch(
        id=batch_id,
        workspace_id=1,
        source_type="official_api",
        status="completed",
        provider_count=1,
        question_count=1,
        repeat_count=2,
        total_tasks=2,
        completed_tasks=2 if complete else 1,
        failed_tasks=0 if complete else 1,
        configuration={"providers": providers, "questions": questions},
        started_at=now,
        completed_at=now,
    )
    db.add(batch)
    db.flush()
    for index, brand_status in enumerate(statuses, start=1):
        evidence_id = batch_id * 10 + index
        observation_run_id = batch_id * 10 + index
        db.add(GeoObservationRun(
            id=observation_run_id,
            workspace_id=1,
            adapter_key="official_api",
            status="completed",
            request_context={},
            started_at=now,
            completed_at=now,
        ))
        evidence = GeoEvidence(
            id=evidence_id,
            workspace_id=1,
            run_id=observation_run_id,
            question_plan_id=1,
            model_key="deepseek",
            model_label="DeepSeek",
            prompt_version="v1",
            sample_mode="api_web_search",
            evidence_level="auditable",
            collection_method="official_api",
            evidence_kind="provider_answer",
            is_real_provider_evidence=True,
            brand_status=brand_status,
            competitor_positions=[],
            answer_text=f"真实回答 {evidence_id}",
            answer_hash=f"{evidence_id:064x}",
            source_items=[{"url": "https://example.com/reference"}],
            sampling_environment={"search_verified": True, "search_event_count": 1},
            raw_artifact_uri=f"file:///evidence/{evidence_id}.json",
            captured_at=now,
        )
        db.add(evidence)
        db.add(GeoObservationTask(
            batch_id=batch_id,
            workspace_id=1,
            evidence_id=evidence_id,
            provider_id=1,
            provider_key="deepseek_web_search",
            provider_label="DeepSeek",
            model_key="deepseek",
            model_label="DeepSeek",
            question_plan_id=1,
            question_text_snapshot="哪家 GEO 平台值得选？",
            sample_key=f"sample:{index}",
            repeat_index=index,
            repeat_count=2,
            status="completed" if complete else ("completed" if index == 1 else "failed"),
            completed_at=now,
        ))
    db.flush()
    return batch


def add_schedule(db: Session, scope: dict) -> None:
    db.add(GeoObservationSchedule(
        id=1, workspace_id=1, name="每日观测", status="active", cadence="daily",
        weekdays=[], local_time="09:00", timezone_name="Asia/Shanghai",
        provider_ids=[1], question_plan_ids=[1], repeat_count=2,
        scope_snapshot=scope, scope_fingerprint=canonical_fingerprint(scope),
        scope_version=1, next_run_at=datetime.now(UTC),
    ))
    db.flush()


def test_next_schedule_treats_sqlite_naive_timestamp_as_utc() -> None:
    next_run = next_schedule_time(
        cadence="daily",
        weekdays=[],
        local_time="09:00",
        timezone_name="Asia/Shanghai",
        after=datetime(2026, 8, 25, 1, 0),
    )
    assert next_run == datetime(2026, 8, 26, 1, 0, tzinfo=UTC)


def test_complete_comparable_drop_creates_one_deduplicated_alert() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Company(id=1, name="测试公司"))
        db.add(GeoWorkspace(id=1, company_id=1, slug="alerts", brand_name="春秋元泉", brand_aliases=[]))
        db.add(GeoQuestionPlan(
            id=1, workspace_id=1, question_text="哪家 GEO 平台值得选？",
            journey_stage="consideration", role="buyer", topic_tags=[], importance=5,
            is_brand_query=False, active=True, status="active", source_type="manual",
            source_evidence={}, template_variables=[],
        ))
        baseline = add_batch(db, 1, statuses=["recommended", "mentioned"])
        current = add_batch(db, 2, statuses=["absent", "absent"])
        scope = schedule_scope([1], [1], 2)
        add_schedule(db, scope)
        run = GeoObservationScheduleRun(
            workspace_id=1, schedule_id=1, window_key="1:2026-08-24T09:00",
            status="running", batch_id=2, baseline_batch_id=1, scope_snapshot=scope,
            scope_fingerprint=canonical_fingerprint(scope), scheduled_for=datetime.now(UTC),
        )
        db.add(run)
        db.flush()
        created = evaluate_change_alerts(db, run=run, current=current, baseline=baseline)
        assert [row.alert_type for row in created] == ["brand.visibility_drop"]
        assert created[0].metric_snapshot["delta"] == -1.0
        db.commit()
        again = evaluate_change_alerts(db, run=run, current=current, baseline=baseline)
        assert again == []
        assert len(list(db.scalars(select(GeoChangeAlert)))) == 1


def test_incomplete_batch_never_emits_false_brand_drop() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Company(id=1, name="测试公司"))
        db.add(GeoWorkspace(id=1, company_id=1, slug="incomplete", brand_name="春秋元泉", brand_aliases=[]))
        db.add(GeoQuestionPlan(
            id=1, workspace_id=1, question_text="哪家 GEO 平台值得选？",
            journey_stage="consideration", role="buyer", topic_tags=[], importance=5,
            is_brand_query=False, active=True, status="active", source_type="manual",
            source_evidence={}, template_variables=[],
        ))
        baseline = add_batch(db, 1, statuses=["recommended", "mentioned"])
        current = add_batch(db, 2, statuses=["absent", "absent"], complete=False)
        scope = schedule_scope([1], [1], 2)
        add_schedule(db, scope)
        run = GeoObservationScheduleRun(
            workspace_id=1, schedule_id=1, window_key="1:2026-08-25T09:00",
            status="running", batch_id=2, baseline_batch_id=1, scope_snapshot=scope,
            scope_fingerprint=canonical_fingerprint(scope), scheduled_for=datetime.now(UTC),
        )
        db.add(run)
        db.flush()
        created = evaluate_change_alerts(db, run=run, current=current, baseline=baseline)
        assert "brand.visibility_drop" not in {row.alert_type for row in created}
        assert "observation.incomplete" in {row.alert_type for row in created}


@pytest.fixture
def alert_api() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with sessions() as db:
        db.add(Company(id=1, name="测试公司"))
        db.add(User(id=1, company_id=1, name="运营员", email="alerts@example.test", role="company_admin"))
        db.add(GeoWorkspace(id=1, company_id=1, slug="alerts-api", brand_name="春秋元泉", brand_aliases=[]))
        db.add(GeoQuestionPlan(
            id=1, workspace_id=1, question_text="哪家 GEO 平台值得选？",
            journey_stage="consideration", role="buyer", topic_tags=[], importance=5,
            is_brand_query=False, active=True, status="active", source_type="manual",
            source_evidence={}, template_variables=[],
        ))
        db.add(LLMProvider(
            id=1, name="DeepSeek", provider_type="deepseek_web_search",
            api_base_url="https://api.deepseek.com", model_name="deepseek-chat",
            auth_config={}, cost_rule={}, status="active",
        ))
        db.flush()
        add_membership(db, workspace_id=1, user_id=1, role="owner")
        db.commit()
    app = create_app()
    actor = SimpleNamespace(id=1, company_id=1, role="company_admin")

    def override_db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: actor
    app.state.alert_sessions = sessions
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
    engine.dispose()


def test_schedule_api_persists_scope_and_dashboard_reads_it(alert_api: TestClient) -> None:
    created = alert_api.post(
        "/api/v1/workspaces/1/observation-schedules",
        json={
            "name": "品牌健康每日观测",
            "cadence": "daily",
            "weekdays": [],
            "local_time": "09:00",
            "timezone_name": "Asia/Shanghai",
            "provider_ids": [1],
            "question_plan_ids": [1],
            "repeat_count": 2,
        },
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["scope_snapshot"] == {
        "schema": "geo-observation-scope/v1",
        "provider_ids": [1],
        "question_plan_ids": [1],
        "repeat_count": 2,
    }
    dashboard = alert_api.get("/api/v1/workspaces/1/observation-alert-center")
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["summary"]["active_schedules"] == 1
    assert dashboard.json()["schedules"][0]["name"] == "品牌健康每日观测"
    paused = alert_api.patch(
        f"/api/v1/workspaces/1/observation-schedules/{payload['id']}",
        json={"status": "paused"},
    )
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"


def test_manual_schedule_run_accepts_dict_batch_and_never_sticks_dispatching(
    alert_api: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.v1 import observation_routes

    created = alert_api.post(
        "/api/v1/workspaces/1/observation-schedules",
        json={
            "name": "最小真实观测",
            "cadence": "daily",
            "weekdays": [],
            "local_time": "09:00",
            "timezone_name": "Asia/Shanghai",
            "provider_ids": [1],
            "question_plan_ids": [1],
            "repeat_count": 1,
        },
    )
    assert created.status_code == 201, created.text
    schedule_id = created.json()["id"]

    monkeypatch.setattr(
        observation_routes,
        "create_provider_web_search_batch",
        lambda *_args, **_kwargs: {"batch_id": 88},
    )
    dispatched = alert_api.post(
        f"/api/v1/workspaces/1/observation-schedules/{schedule_id}/run"
    )
    assert dispatched.status_code == 202, dispatched.text
    assert dispatched.json()["status"] == "running"
    assert dispatched.json()["batch_id"] == 88

    def fail_dispatch(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        observation_routes, "create_provider_web_search_batch", fail_dispatch
    )
    failed = alert_api.post(
        f"/api/v1/workspaces/1/observation-schedules/{schedule_id}/run"
    )
    assert failed.status_code == 500, failed.text
    assert "观测计划分发失败" in failed.json()["detail"]

    sessions = alert_api.app.state.alert_sessions
    with sessions() as db:
        runs = list(
            db.scalars(
                select(GeoObservationScheduleRun).order_by(
                    GeoObservationScheduleRun.id.asc()
                )
            )
        )
        assert [run.status for run in runs] == ["running", "failed"]
        assert runs[0].batch_id == 88
        assert runs[1].completed_at is not None
        assert runs[1].failure_reason == "provider unavailable"
        assert all(run.status != "dispatching" for run in runs)


def test_repair_retries_only_latest_worker_interruption_once(
    alert_api: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.v1 import observation_routes

    created = alert_api.post(
        "/api/v1/workspaces/1/observation-schedules",
        json={
            "name": "Worker 中断补跑",
            "cadence": "daily",
            "weekdays": [],
            "local_time": "09:00",
            "timezone_name": "Asia/Shanghai",
            "provider_ids": [1],
            "question_plan_ids": [1],
            "repeat_count": 1,
        },
    )
    assert created.status_code == 201, created.text
    schedule_id = created.json()["id"]
    sessions = alert_api.app.state.alert_sessions
    with sessions() as db:
        schedule = db.get(GeoObservationSchedule, schedule_id)
        assert schedule is not None
        db.add(
            GeoObservationScheduleRun(
                workspace_id=1,
                schedule_id=schedule_id,
                window_key="1:worker-offline",
                status="failed",
                scope_snapshot=schedule.scope_snapshot,
                scope_fingerprint=schedule.scope_fingerprint,
                scheduled_for=datetime.now(UTC),
                completed_at=datetime.now(UTC),
                failure_reason="采集服务当前离线，本次任务尚未创建。",
            )
        )
        db.commit()

    monkeypatch.setattr(
        observation_routes,
        "create_provider_web_search_batch",
        lambda *_args, **_kwargs: {"batch_id": 77},
    )
    with sessions() as db:
        actor = db.get(User, 1)
        assert actor is not None
        result = retry_worker_interrupted_schedule_runs(
            db, workspace_id=1, actor=actor, limit=3
        )
        assert result["retried"] == 1
        assert result["failed"] == 0
        latest = db.scalar(
            select(GeoObservationScheduleRun)
            .where(GeoObservationScheduleRun.schedule_id == schedule_id)
            .order_by(GeoObservationScheduleRun.id.desc())
        )
        assert latest is not None
        assert latest.status == "running"
        assert latest.batch_id == 77

        second = retry_worker_interrupted_schedule_runs(
            db, workspace_id=1, actor=actor, limit=3
        )
        assert second["retried"] == 0
