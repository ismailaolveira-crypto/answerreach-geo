from collections.abc import Generator
from datetime import datetime, timezone
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
from app.models import QueueJob
from app.models.company import Company
from app.models.cleanroom_v1 import (
    GeoActionCompletionEvidence,
    GeoActionOpportunity,
    GeoActionTarget,
    GeoDistributionRun,
    GeoDistributionTarget,
    GeoEvidence,
    GeoObservationBatch,
    GeoObservationRun,
    GeoObservationTask,
    GeoOptimizationAction,
    GeoQuestionPlan,
    GeoWorkspace,
)
from app.models.user import User
from app.services.workspace_access import add_membership
from app.v1 import routes


def _evidence(evidence_id: int, run_id: int, model_key: str, brand_status: str) -> GeoEvidence:
    now = datetime.now(timezone.utc)
    return GeoEvidence(
        id=evidence_id,
        workspace_id=1,
        run_id=run_id,
        question_plan_id=1,
        model_key=model_key,
        model_label=model_key,
        prompt_version="v1",
        sample_mode="api_web_search",
        evidence_level="auditable",
        collection_method="official_api",
        evidence_kind="provider_answer",
        is_real_provider_evidence=True,
        brand_status=brand_status,
        brand_position=1 if brand_status != "absent" else None,
        competitor_positions=[],
        answer_text=f"真实联网回答 {evidence_id}",
        answer_hash=f"{evidence_id:064x}",
        source_items=[{"url": f"https://example.com/source/{evidence_id}"}],
        sampling_environment={"search_verified": True, "search_event_count": 2},
        raw_artifact_uri=f"file:///private/retest/{evidence_id}.json",
        captured_at=now,
    )


@pytest.fixture
def retest_client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    provider_snapshots = [
        {"id": 10, "key": "deepseek", "label": "DeepSeek", "model_name": "deepseek-v4"},
        {"id": 20, "key": "qianwen", "label": "通义千问", "model_name": "qwen-plus"},
    ]
    with session_factory() as db:
        db.add(Company(id=1, name="测试公司"))
        db.add(User(id=1, company_id=1, name="运营员", email="ops@example.com", role="company_admin"))
        db.add(
            GeoWorkspace(
                id=1,
                company_id=1,
                slug="retest-workspace",
                brand_name="春秋元泉",
                brand_aliases=[],
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
                adapter_key="official_api",
                status="completed",
                request_context={},
                started_at=now,
                completed_at=now,
            )
        )
        db.add(
            GeoObservationBatch(
                id=1,
                workspace_id=1,
                source_type="official_api",
                status="completed",
                provider_count=2,
                question_count=1,
                repeat_count=2,
                total_tasks=4,
                completed_tasks=4,
                failed_tasks=0,
                configuration={
                    "providers": provider_snapshots,
                    "questions": [{"id": 1, "key": "1", "label": "Token 统一管控平台哪家好？"}],
                },
                started_at=now,
                completed_at=now,
            )
        )
        db.add(
            GeoActionOpportunity(
                id=1,
                workspace_id=1,
                fingerprint="a" * 64,
                opportunity_type="candidate_gap",
                title="补齐品牌答案",
                summary="基线未出现品牌",
                priority_score=92,
                priority_label="high",
                evidence_strength=1,
                source_gap_type="owned_content",
                recommended_asset_type="article",
                recommended_platforms=["zhihu", "wechat"],
                scope_snapshot={"batch_id": 1, "question_plan_id": 1},
                rule_version="opportunity.v1",
                status="selected",
                first_seen_batch_id=1,
                latest_seen_batch_id=1,
            )
        )
        db.add(
            GeoOptimizationAction(
                id=1,
                workspace_id=1,
                opportunity_id=1,
                question_plan_id=1,
                title="补齐品牌答案",
                rationale="基线未出现品牌",
                priority="high",
                status="in_progress",
                stage="ready_for_retest",
                baseline_snapshot={"batch_id": 1, "model_keys": ["deepseek"]},
                selected_scope={},
            )
        )
        db.add(
            GeoDistributionRun(
                id=1,
                workspace_id=1,
                action_id=1,
                requested_platforms=["zhihu", "wechat"],
                stage="published",
                idempotency_key="published-run-1",
                status="published",
                requested_by_user_id=1,
            )
        )
        db.add_all(
            [
                GeoDistributionTarget(
                    id=1,
                    distribution_run_id=1,
                    platform_key="zhihu",
                    request_status="draft_saved",
                    draft_readback_status="draft_saved",
                    draft_url="https://www.zhihu.com/draft/1",
                    human_publish_status="published",
                    public_url="https://zhuanlan.zhihu.com/p/123",
                    publication_verification_status="publicly_verified",
                    published_at=now,
                    published_by_user_id=1,
                ),
                GeoDistributionTarget(
                    id=2,
                    distribution_run_id=1,
                    platform_key="wechat",
                    request_status="draft_saved",
                    draft_readback_status="draft_saved",
                    draft_url="https://mp.weixin.qq.com/draft/2",
                    human_publish_status="published",
                    public_url="https://mp.weixin.qq.com/s/example",
                    publication_verification_status="publicly_verified",
                    published_at=now,
                    published_by_user_id=1,
                ),
            ]
        )
        evidence_id = 1
        for provider in provider_snapshots:
            for repeat_index in (1, 2):
                evidence = _evidence(evidence_id, 1, provider["key"], "absent")
                db.add(evidence)
                db.add(
                    GeoObservationTask(
                        batch_id=1,
                        workspace_id=1,
                        run_id=1,
                        evidence_id=evidence_id,
                        provider_id=provider["id"],
                        provider_key="official_api",
                        provider_label=provider["label"],
                        model_key=provider["key"],
                        model_label=provider["label"],
                        question_plan_id=1,
                        question_text_snapshot="Token 统一管控平台哪家好？",
                        sample_key=f"baseline:{provider['id']}:{repeat_index}",
                        repeat_index=repeat_index,
                        repeat_count=2,
                        status="completed",
                        completed_at=now,
                    )
                )
                evidence_id += 1
        db.flush()
        add_membership(db, workspace_id=1, user_id=1, role="owner")
        db.commit()

    captured_payload = {}

    def fake_create_batch(workspace_id, payload, db, user):
        captured_payload.update(payload.model_dump())
        parent = QueueJob(
            job_type="geo_observation.batch",
            status="running",
            priority=0,
            attempts=0,
            max_attempts=1,
            scheduled_at=now,
            started_at=now,
            payload_json={},
        )
        db.add(parent)
        db.flush()
        ledger = GeoObservationBatch(
            workspace_id=workspace_id,
            queue_job_id=parent.id,
            source_type="official_api",
            status="running",
            provider_count=2,
            question_count=1,
            repeat_count=2,
            total_tasks=4,
            completed_tasks=0,
            failed_tasks=0,
            configuration={
                "providers": provider_snapshots,
                "questions": [{"id": 1, "key": "1", "label": "Token 统一管控平台哪家好？"}],
            },
            started_at=now,
        )
        db.add(ledger)
        db.flush()
        child_ids = []
        for provider in provider_snapshots:
            for repeat_index in (1, 2):
                child = QueueJob(
                    job_type="geo_observation.collect",
                    status="pending",
                    priority=10,
                    attempts=0,
                    max_attempts=3,
                    scheduled_at=now,
                    payload_json={
                        "provider_id": provider["id"],
                        "provider_key": provider["key"],
                        "provider_label": provider["label"],
                        "question_plan_id": 1,
                        "question_label": "Token 统一管控平台哪家好？",
                        "repeat_index": repeat_index,
                    },
                )
                db.add(child)
                db.flush()
                child_ids.append(child.id)
                db.add(
                    GeoObservationTask(
                        batch_id=ledger.id,
                        workspace_id=1,
                        queue_job_id=child.id,
                        provider_id=provider["id"],
                        provider_key="official_api",
                        provider_label=provider["label"],
                        model_key=provider["key"],
                        model_label=provider["label"],
                        question_plan_id=1,
                        question_text_snapshot="Token 统一管控平台哪家好？",
                        sample_key=f"retest:{provider['id']}:{repeat_index}",
                        repeat_index=repeat_index,
                        repeat_count=2,
                        status="pending",
                    )
                )
        parent.payload_json = {
            "provider_count": 2,
            "question_count": 1,
            "repeat_count": 2,
            "total": 4,
            "providers": provider_snapshots,
            "questions": [{"id": 1, "key": "1", "label": "Token 统一管控平台哪家好？"}],
            "child_job_ids": child_ids,
            "observation_ledger_batch_id": ledger.id,
        }
        db.commit()
        # Match the real observation-batch endpoint: batch_id identifies the
        # persisted ledger, while queue_job_id is a separate parent receipt.
        assert ledger.id != parent.id
        return {"batch_id": ledger.id}

    monkeypatch.setattr(routes, "create_provider_web_search_batch", fake_create_batch)
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1, company_id=1, role="company_admin"
    )
    client = TestClient(app)
    client.app.state.retest_session_factory = session_factory
    client.app.state.captured_retest_payload = captured_payload
    yield client
    app.dependency_overrides.clear()


def test_retest_reuses_exact_scope_and_completes_from_real_evidence(
    retest_client: TestClient,
) -> None:
    queued = retest_client.post("/api/v1/workspaces/1/actions/1/retest")
    assert queued.status_code == 202
    assert queued.json()["status"] == "queued"
    assert queued.json()["batch"]["progress_percent"] == 0
    assert queued.json()["retest_batch_id"] != queued.json()["retest_queue_job_id"]
    assert retest_client.app.state.captured_retest_payload == {
        "provider_ids": [10],
        "question_plan_ids": [1],
        "repeat_count": 2,
    }

    idempotent_publication = retest_client.post(
        "/api/v1/workspaces/1/distribution-runs/1/targets/1/human-publication",
        json={"public_url": "https://zhuanlan.zhihu.com/p/123"},
    )
    assert idempotent_publication.status_code == 200

    locked_publication = retest_client.post(
        "/api/v1/workspaces/1/distribution-runs/1/targets/1/human-publication",
        json={"public_url": "https://www.zhihu.com/question/123/answer/456"},
    )
    assert locked_publication.status_code == 409
    assert "已锁定" in locked_publication.json()["detail"]

    session_factory = retest_client.app.state.retest_session_factory
    with session_factory() as db:
        row = db.scalar(select(models.GeoReobservation).where(models.GeoReobservation.action_id == 1))
        assert row is not None
        db.add(
            GeoObservationRun(
                id=2,
                workspace_id=1,
                adapter_key="official_api",
                status="completed",
                request_context={},
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
        )
        tasks = list(
            db.scalars(
                select(GeoObservationTask)
                .where(GeoObservationTask.batch_id == row.retest_batch_id)
                .order_by(GeoObservationTask.id)
            )
        )
        for index, task in enumerate(tasks, start=101):
            evidence = _evidence(
                index,
                2,
                task.model_key,
                "recommended" if index == 101 else "absent",
            )
            db.add(evidence)
            task.run_id = 2
            task.evidence_id = index
            task.status = "completed"
            task.completed_at = datetime.now(timezone.utc)
            child = db.get(QueueJob, task.queue_job_id)
            assert child is not None
            child.status = "success"
            child.started_at = datetime.now(timezone.utc)
            child.finished_at = datetime.now(timezone.utc)
        db.commit()

    # Reading is pure; an explicit refresh advances a finished retest.
    completed = retest_client.post("/api/v1/workspaces/1/actions/1/retest/refresh")
    assert completed.status_code == 200
    payload = completed.json()
    assert payload["status"] == "completed"
    assert payload["batch"]["progress_percent"] == 100
    assert payload["conclusion"] == "improved"
    assert payload["measured_delta"]["comparable"] is True
    assert payload["baseline_metrics"]["eligible_samples"] == 2
    assert payload["retest_metrics"]["eligible_samples"] == 2
    assert payload["retest_metrics"]["positive_count"] == 1

    with session_factory() as db:
        action = db.get(GeoOptimizationAction, 1)
        opportunity = db.get(GeoActionOpportunity, 1)
        assert action is not None
        assert opportunity is not None
        assert action.status == "verified"
        assert action.stage == "verified"
        assert opportunity.status == "selected"

    second_round = retest_client.post("/api/v1/workspaces/1/actions/1/retest")
    assert second_round.status_code == 202
    assert second_round.json()["round_index"] == 2
    with session_factory() as db:
        rows = list(
            db.scalars(
                select(models.GeoReobservation)
                .where(models.GeoReobservation.action_id == 1)
                .order_by(models.GeoReobservation.round_index)
            )
        )
        assert [row.round_index for row in rows] == [1, 2]
        assert rows[0].status == "completed"

    unresolved = retest_client.get("/api/v1/workspaces/1/action-opportunities")
    assert unresolved.status_code == 200
    assert len(unresolved.json()) == 1


def test_legacy_single_evidence_cannot_mark_action_verified(
    retest_client: TestClient,
) -> None:
    response = retest_client.post(
        "/api/v1/workspaces/1/actions/1/re-observations",
        json={
            "run_id": 1,
            "evidence_id": 1,
            "conclusion": "improved",
            "measured_delta": {"mention_rate": 1},
        },
    )
    assert response.status_code == 201
    assert response.json()["status"] == "in_progress"

    session_factory = retest_client.app.state.retest_session_factory
    with session_factory() as db:
        action = db.get(GeoOptimizationAction, 1)
        row = db.scalar(select(models.GeoReobservation).where(models.GeoReobservation.action_id == 1))
        assert action is not None
        assert row is not None
        assert action.stage == "retest_inconclusive"
        assert row.status == "legacy_recorded"
        assert row.conclusion == "insufficient_evidence"
        assert row.measured_delta["comparable"] is False


def test_v2_retest_uses_only_selected_completed_target(
    retest_client: TestClient,
) -> None:
    session_factory = retest_client.app.state.retest_session_factory
    now = datetime.now(timezone.utc)
    with session_factory() as db:
        action = db.get(GeoOptimizationAction, 1)
        assert action is not None
        action.action_type = "article"
        action.deliverable_type = "article_asset"
        action.workflow_version = "action-flow.v2"
        action.affected_question_ids = [1]
        action.affected_model_keys = ["deepseek"]
        action.scope_fingerprint = "f" * 64
        action.measurement_status = "eligible"
        db.add_all(
            [
                GeoActionTarget(
                    id=11,
                    workspace_id=1,
                    action_id=1,
                    target_key="article:zhihu",
                    target_type="platform",
                    platform_key="zhihu",
                    display_name="知乎",
                    target_ref="zhihu",
                    delivery_status="publicly_verified",
                    ordinal=1,
                    metadata_json={},
                    completed_at=now,
                    completed_by_user_id=1,
                    verified_at=now,
                ),
                GeoActionTarget(
                    id=12,
                    workspace_id=1,
                    action_id=1,
                    target_key="article:wechat",
                    target_type="platform",
                    platform_key="wechat",
                    display_name="微信公众号",
                    target_ref="wechat",
                    delivery_status="drafting",
                    ordinal=2,
                    metadata_json={},
                ),
            ]
        )
        db.flush()
        db.add(
            GeoActionCompletionEvidence(
                id=21,
                workspace_id=1,
                action_id=1,
                target_id=11,
                evidence_type="public_url",
                source_url="https://zhuanlan.zhihu.com/p/123",
                sha256="e" * 64,
                verification_status="verified",
                detail={"readback": True},
                submitted_by_user_id=1,
                verified_by_user_id=1,
                submitted_at=now,
                verified_at=now,
                idempotency_key="target-evidence-21",
            )
        )
        db.commit()

    queued = retest_client.post(
        "/api/v1/workspaces/1/actions/1/retests",
        json={"target_ids": [11], "idempotency_key": "target-retest-round-1"},
    )
    assert queued.status_code == 202
    payload = queued.json()
    assert payload["scope_snapshot"]["schema"] == "target-action-retest/v3"
    assert payload["scope_snapshot"]["action_target_ids"] == [11]
    assert payload["target_evidence"] == [
        {
            "action_target_id": 11,
            "completion_evidence_id": 21,
            "evidence_sha256": "e" * 64,
            "scope_fingerprint": "f" * 64,
        }
    ]

    with session_factory() as db:
        action = db.get(GeoOptimizationAction, 1)
        assert action is not None
        assert action.stage == "ready_for_retest"
        assert action.measurement_status == "retesting"

    idempotent = retest_client.post(
        "/api/v1/workspaces/1/actions/1/retests",
        json={"target_ids": [11], "idempotency_key": "target-retest-round-1"},
    )
    assert idempotent.status_code == 202
    assert idempotent.json()["id"] == payload["id"]

    different_scope = retest_client.post(
        "/api/v1/workspaces/1/actions/1/retests",
        json={"target_ids": [12], "idempotency_key": "target-retest-round-1"},
    )
    assert different_scope.status_code == 409

    with session_factory() as db:
        row = db.scalar(select(models.GeoReobservation).where(models.GeoReobservation.action_id == 1))
        assert row is not None
        db.add(
            GeoObservationRun(
                id=3,
                workspace_id=1,
                adapter_key="official_api",
                status="completed",
                request_context={},
                started_at=now,
                completed_at=now,
            )
        )
        tasks = list(
            db.scalars(
                select(GeoObservationTask)
                .where(GeoObservationTask.batch_id == row.retest_batch_id)
                .order_by(GeoObservationTask.id)
            )
        )
        for index, task in enumerate(tasks, start=301):
            db.add(_evidence(index, 3, task.model_key, "mentioned"))
            task.run_id = 3
            task.evidence_id = index
            task.status = "completed"
            task.completed_at = now
            child = db.get(QueueJob, task.queue_job_id)
            assert child is not None
            child.status = "success"
            child.started_at = now
            child.finished_at = now
        db.commit()

    completed = retest_client.post("/api/v1/workspaces/1/actions/1/retest/refresh")
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    with session_factory() as db:
        action = db.get(GeoOptimizationAction, 1)
        assert action is not None
        assert action.stage == "ready_for_retest"
        assert action.measurement_status == "measured"
        links = list(
            db.scalars(
                select(models.GeoReobservationTarget).where(
                    models.GeoReobservationTarget.reobservation_id == completed.json()["id"]
                )
            )
        )
        assert [(link.action_target_id, link.completion_evidence_id) for link in links] == [(11, 21)]
