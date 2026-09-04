from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
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
    GeoActionApproval,
    GeoActionCompletionEvidence,
    GeoActionEvent,
    GeoActionTarget,
    GeoContentAsset,
    GeoContentBrief,
    GeoDistributionRun,
    GeoDistributionTarget,
    GeoOptimizationAction,
    GeoPlatformVariant,
    GeoWorkspace,
)
from app.models.user import User
from app.services.workspace_access import add_membership
from app.v1 import action_workflow, action_workflow_routes


@pytest.fixture
def workflow_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, dict[str, SimpleNamespace]], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    users = {
        "owner": SimpleNamespace(id=1, company_id=1, role="company_admin"),
        "operator": SimpleNamespace(id=2, company_id=1, role="content_operator"),
        "reviewer": SimpleNamespace(id=3, company_id=1, role="reviewer"),
        "viewer": SimpleNamespace(id=4, company_id=1, role="viewer"),
    }
    with sessions() as db:
        db.add(Company(id=1, name="测试企业"))
        db.add_all(
            [
                User(id=1, company_id=1, name="负责人", email="owner-v2@example.test", role="company_admin"),
                User(id=2, company_id=1, name="执行人", email="operator-v2@example.test", role="content_operator"),
                User(id=3, company_id=1, name="审批人", email="reviewer-v2@example.test", role="reviewer"),
                User(id=4, company_id=1, name="只读成员", email="viewer-v2@example.test", role="viewer"),
            ]
        )
        db.add(
            GeoWorkspace(
                id=1,
                company_id=1,
                slug="action-workflow-v2",
                brand_name="春秋元泉",
                brand_aliases=[],
                website_url="https://example.com",
            )
        )
        db.flush()
        add_membership(db, workspace_id=1, user_id=1, role="owner")
        add_membership(db, workspace_id=1, user_id=2, role="operator")
        add_membership(db, workspace_id=1, user_id=3, role="reviewer")
        add_membership(db, workspace_id=1, user_id=4, role="viewer")
        db.add(
            GeoOptimizationAction(
                id=1,
                workspace_id=1,
                title="补齐知乎品牌解释文章",
                rationale="目标问题仍缺少品牌答案",
                hypothesis="公开并被引用后可见度应改善",
                priority="high",
                status="proposed",
                stage="proposed",
                baseline_snapshot={"batch_id": 10},
                selected_scope={"batch_ids": [10], "question_ids": [1]},
                measurement_plan={},
                action_type="article",
                deliverable_type="platform_article",
                workflow_version="action-flow.v2",
                affected_question_ids=[1],
                affected_model_keys=["deepseek", "qwen"],
                scope_fingerprint="a" * 64,
                measurement_status="not_eligible",
            )
        )
        db.add(
            GeoActionTarget(
                id=1,
                workspace_id=1,
                action_id=1,
                target_key="zhihu-main",
                target_type="platform",
                platform_key="zhihu",
                display_name="知乎",
                target_ref="zhihu",
                delivery_status="target_selected",
                ordinal=0,
                metadata_json={},
            )
        )
        db.commit()

    app = create_app()
    current = {"user": users["owner"]}

    def override_db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: current["user"]
    monkeypatch.setattr(
        action_workflow_routes,
        "verify_publication_page",
        lambda url: {
            "status": "publicly_verified",
            "verified_url": url,
            "status_code": 200,
            "content_type": "text/html",
            "sha256": "b" * 64,
            "size_bytes": 2048,
            "verified_at": datetime.now(UTC).isoformat(),
        },
    )
    monkeypatch.setattr(
        action_workflow_routes,
        "verify_structured_data_page",
        lambda url, expected_types: {
            "status": "schema_validated",
            "verified_url": url,
            "status_code": 200,
            "content_type": "text/html",
            "sha256": "c" * 64,
            "size_bytes": 3072,
            "verified_at": datetime.now(UTC).isoformat(),
            "matched_types": expected_types or ["Organization"],
        },
    )
    client = TestClient(app)
    client.app.state.workflow_sessions = sessions
    client.app.state.current_user = current
    yield client, users
    app.dependency_overrides.clear()
    engine.dispose()


def _set_user(client: TestClient, user: SimpleNamespace) -> None:
    client.app.state.current_user["user"] = user


def test_stale_issued_distribution_does_not_mask_newer_retry_ready_state(
    workflow_client: tuple[TestClient, dict[str, SimpleNamespace]],
) -> None:
    client, _users = workflow_client
    sessions = client.app.state.workflow_sessions
    issued_at = datetime.now(UTC) - timedelta(hours=1)
    with sessions() as db:
        action = db.get(GeoOptimizationAction, 1)
        target = db.get(GeoActionTarget, 1)
        db.add_all(
            [
                GeoDistributionRun(
                    id=1,
                    workspace_id=1,
                    action_id=1,
                    requested_platforms=["zhihu"],
                    stage="failed",
                    idempotency_key="stale-issued-run",
                    status="failed",
                    requested_by_user_id=1,
                    assistant_task_issued_at=issued_at,
                ),
                GeoDistributionTarget(
                    id=1,
                    distribution_run_id=1,
                    platform_key="zhihu",
                    request_status="failed",
                    draft_readback_status="not_checked",
                ),
                GeoDistributionRun(
                    id=2,
                    workspace_id=1,
                    action_id=1,
                    requested_platforms=["zhihu"],
                    stage="requested",
                    idempotency_key="new-retry-run",
                    status="pending",
                    requested_by_user_id=1,
                ),
                GeoDistributionTarget(
                    id=2,
                    distribution_run_id=2,
                    platform_key="zhihu",
                    request_status="not_started",
                    draft_readback_status="not_checked",
                ),
            ]
        )
        db.commit()

        delivery_status, source, _message, target_id = action_workflow._article_target_truth(
            db, action, target
        )

    assert delivery_status == "draft_ready"
    assert source == "distribution_target"
    assert target_id == 2


def _transition(client: TestClient, to_status: str, key: str) -> dict:
    response = client.post(
        "/api/v1/workspaces/1/actions/1/targets/1/transition",
        json={"to_status": to_status, "idempotency_key": key},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _transition_target(
    client: TestClient,
    action_id: int,
    target_id: int,
    to_status: str,
    key: str,
) -> dict:
    response = client.post(
        f"/api/v1/workspaces/1/actions/{action_id}/targets/{target_id}/transition",
        json={"to_status": to_status, "idempotency_key": key},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _approve_target(
    client: TestClient,
    users: dict[str, SimpleNamespace],
    *,
    action_id: int,
    target_id: int,
    approval_type: str,
) -> None:
    response = client.post(
        f"/api/v1/workspaces/1/actions/{action_id}/approvals",
        json={
            "target_id": target_id,
            "approval_type": approval_type,
            "reviewer_user_id": 3,
            "due_at": (datetime.now(UTC) + timedelta(hours=12)).isoformat(),
            "subject_fingerprint": f"{action_id:064x}",
        },
    )
    assert response.status_code == 201, response.text
    _set_user(client, users["reviewer"])
    decided = client.post(
        f"/api/v1/workspaces/1/actions/{action_id}/approvals/{response.json()['id']}/decide",
        json={"decision": "approved"},
    )
    assert decided.status_code == 200, decided.text
    _set_user(client, users["owner"])


def _submit_target_evidence(
    client: TestClient,
    *,
    action_id: int,
    target_id: int,
    evidence_type: str,
    source_url: str,
) -> dict:
    response = client.post(
        f"/api/v1/workspaces/1/actions/{action_id}/targets/{target_id}/evidence",
        json={
            "evidence_type": evidence_type,
            "source_url": source_url,
            "detail": {"expected_types": ["Organization"]}
            if evidence_type == "schema_validation"
            else {},
            "idempotency_key": f"{action_id}-{target_id}-{evidence_type}",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["verification_status"] == "verified"
    return response.json()


def test_article_action_uses_content_distribution_and_publication_as_authoritative_state(
    workflow_client: tuple[TestClient, dict[str, SimpleNamespace]],
) -> None:
    client, users = workflow_client
    detail = client.get("/api/v1/workspaces/1/actions/1")
    assert detail.status_code == 200
    assert detail.json()["next_action"] == "分配负责人并接受"

    due_at = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    accepted = client.post(
        "/api/v1/workspaces/1/actions/1/accept",
        json={"assignee_user_id": 2, "due_at": due_at},
    )
    assert accepted.status_code == 200
    assert accepted.json()["stage"] == "accepted"
    assert accepted.json()["assignee_user_id"] == 2

    _set_user(client, users["viewer"])
    forbidden = client.post(
        "/api/v1/workspaces/1/actions/1/assign",
        json={"assignee_user_id": 4, "reason": "越权尝试"},
    )
    assert forbidden.status_code == 403
    _set_user(client, users["owner"])

    manual_transition = client.post(
        "/api/v1/workspaces/1/actions/1/targets/1/transition",
        json={"to_status": "variant_generating", "idempotency_key": "manual-state-is-rejected"},
    )
    assert manual_transition.status_code == 409

    sessions = client.app.state.workflow_sessions
    with sessions() as db:
        db.add(
            GeoContentBrief(
                id=1,
                workspace_id=1,
                action_id=1,
                audience="企业采购负责人",
                intent="consideration",
                asset_type="article",
                required_sections=[],
                brand_fact_ids=[],
                evidence_ids=[],
                source_urls=[],
                required_claims=[],
                forbidden_claims=[],
                open_questions=[],
                input_fingerprint="1" * 64,
                status="ready",
            )
        )
        db.add(
            GeoContentAsset(
                id=1,
                workspace_id=1,
                brief_id=1,
                version=1,
                title="知乎测试稿",
                summary="摘要",
                body_markdown="正文",
                content_fingerprint="2" * 64,
                generation_usage={},
                status="approved",
            )
        )
        db.add(
            GeoPlatformVariant(
                id=1,
                workspace_id=1,
                content_asset_id=1,
                platform_key="zhihu",
                version=1,
                policy_version="zhihu.v1",
                title="知乎测试稿",
                summary="摘要",
                body_markdown="正文",
                tags=[],
                image_manifest=[],
                adaptation_contract={},
                content_fingerprint="3" * 64,
                status="approved",
            )
        )
        db.add(
            GeoDistributionRun(
                id=1,
                workspace_id=1,
                action_id=1,
                content_asset_id=1,
                requested_platforms=["zhihu"],
                stage="draft_saved",
                idempotency_key="test-authoritative-article-state",
                status="draft_saved",
                requested_by_user_id=1,
            )
        )
        db.add(
            GeoDistributionTarget(
                id=1,
                distribution_run_id=1,
                platform_variant_id=1,
                platform_key="zhihu",
                adapter_version="browser-extension.v1",
                request_status="draft_saved",
                draft_readback_status="draft_saved",
                candidate_draft_url="https://zhuanlan.zhihu.com/p/123456/edit",
                draft_url="https://zhuanlan.zhihu.com/p/123456/edit",
                human_publish_status="awaiting_publish",
                publication_verification_status="not_checked",
                final_action_clicked=False,
            )
        )
        db.add(
            GeoDistributionRun(
                id=2,
                workspace_id=1,
                action_id=1,
                content_asset_id=1,
                requested_platforms=["zhihu"],
                stage="queued",
                idempotency_key="test-newer-weaker-article-state",
                status="pending",
                requested_by_user_id=1,
            )
        )
        db.add(
            GeoDistributionTarget(
                id=2,
                distribution_run_id=2,
                platform_variant_id=1,
                platform_key="zhihu",
                adapter_version="browser-extension.v1",
                request_status="not_started",
                draft_readback_status="not_checked",
                human_publish_status="not_published",
                publication_verification_status="not_checked",
                final_action_clicked=False,
            )
        )
        db.commit()

    draft_ready = client.get("/api/v1/workspaces/1/actions/1").json()
    assert draft_ready["targets"][0]["delivery_status"] == "awaiting_human_publish"
    assert draft_ready["targets"][0]["status_source"] == "draft_readback"

    evidence = client.post(
        "/api/v1/workspaces/1/actions/1/targets/1/evidence",
        json={
            "evidence_type": "public_url",
            "source_url": "https://zhuanlan.zhihu.com/p/123456",
            "detail": {"title": "公开文章"},
            "idempotency_key": "article-public-evidence-01",
        },
    )
    assert evidence.status_code == 201, evidence.text
    assert evidence.json()["verification_status"] == "verified"
    assert evidence.json()["sha256"] == "b" * 64

    completed = client.get("/api/v1/workspaces/1/actions/1").json()
    assert completed["stage"] == "ready_for_retest"
    assert completed["measurement_status"] == "eligible"
    assert completed["completed_target_count"] == 1
    assert completed["retest_eligible_target_count"] == 1
    assert completed["eligible_target_ids"] == [1]

    with sessions() as db:
        assert len(list(db.scalars(select(GeoActionApproval)))) == 0
        assert len(list(db.scalars(select(GeoActionCompletionEvidence)))) == 1
        completion_events = list(
            db.scalars(
                select(GeoActionEvent).where(
                    GeoActionEvent.event_type
                    == "action_target_completed_from_verified_evidence"
                )
            )
        )
        assert len(completion_events) == 1


def test_article_review_and_status_cannot_be_advanced_without_real_content_records(
    workflow_client: tuple[TestClient, dict[str, SimpleNamespace]],
) -> None:
    client, _users = workflow_client
    due_at = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    assert client.post(
        "/api/v1/workspaces/1/actions/1/accept",
        json={"assignee_user_id": 2, "due_at": due_at},
    ).status_code == 200
    response = client.post(
        "/api/v1/workspaces/1/actions/1/targets/1/self-approve"
    )
    assert response.status_code == 409
    assert "实际内容版本" in response.json()["detail"]

    sessions = client.app.state.workflow_sessions
    with sessions() as db:
        assert list(db.scalars(select(GeoActionApproval))) == []


def test_operator_can_block_own_action_but_viewer_cannot_mutate(
    workflow_client: tuple[TestClient, dict[str, SimpleNamespace]],
) -> None:
    client, users = workflow_client
    assert client.post(
        "/api/v1/workspaces/1/actions/1/accept",
        json={
            "assignee_user_id": 2,
            "due_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
        },
    ).status_code == 200
    _set_user(client, users["operator"])
    blocked = client.post(
        "/api/v1/workspaces/1/actions/1/block",
        json={"reason_code": "waiting_owner", "note": "等待品牌负责人确认"},
    )
    assert blocked.status_code == 200
    assert blocked.json()["stage"] == "blocked"
    assert blocked.json()["blocked_reason_code"] == "waiting_owner"
    unblocked = client.post(
        "/api/v1/workspaces/1/actions/1/unblock",
        json={"note": "负责人已确认"},
    )
    assert unblocked.status_code == 200
    assert unblocked.json()["stage"] == "accepted"
    assert unblocked.json()["blocked_reason_code"] is None

    _set_user(client, users["viewer"])
    denied = client.post(
        "/api/v1/workspaces/1/actions/1/block",
        json={"reason_code": "other", "note": "只读成员不能修改"},
    )
    assert denied.status_code == 403


def test_non_article_actions_keep_distinct_workflows_and_real_completion_evidence(
    workflow_client: tuple[TestClient, dict[str, SimpleNamespace]],
) -> None:
    client, users = workflow_client
    sessions = client.app.state.workflow_sessions
    definitions = [
        {
            "id": 2,
            "title": "补齐官网选型页",
            "action_type": "official_site",
            "deliverable_type": "official_page_change",
            "target_type": "official_page",
            "display_name": "官网产品页",
            "target_ref": "https://example.com/product",
            "status": "gap_confirmed",
        },
        {
            "id": 3,
            "title": "补齐 Organization JSON-LD",
            "action_type": "structured_data",
            "deliverable_type": "json_ld",
            "target_type": "schema",
            "display_name": "Organization Schema",
            "target_ref": "https://example.com/product",
            "status": "schema_gap_confirmed",
        },
        {
            "id": 4,
            "title": "建设知乎行业信源",
            "action_type": "third_party_source",
            "deliverable_type": "external_public_content",
            "target_type": "external_source",
            "display_name": "知乎行业专栏",
            "target_ref": "https://zhuanlan.zhihu.com/example",
            "status": "source_selected",
        },
    ]
    with sessions() as db:
        for definition in definitions:
            action_id = definition["id"]
            db.add(
                GeoOptimizationAction(
                    id=action_id,
                    workspace_id=1,
                    title=definition["title"],
                    rationale="需要独立交付流程",
                    hypothesis="完成并回读后才允许复测",
                    priority="high",
                    status="proposed",
                    stage="proposed",
                    baseline_snapshot={"batch_id": 10},
                    selected_scope={"batch_ids": [10], "question_ids": [action_id]},
                    measurement_plan={},
                    action_type=definition["action_type"],
                    deliverable_type=definition["deliverable_type"],
                    workflow_version="action-flow.v2",
                    affected_question_ids=[action_id],
                    affected_model_keys=["deepseek"],
                    scope_fingerprint=f"{action_id:064x}",
                    measurement_status="not_eligible",
                )
            )
            db.add(
                GeoActionTarget(
                    id=action_id,
                    workspace_id=1,
                    action_id=action_id,
                    target_key=f"target-{action_id}",
                    target_type=definition["target_type"],
                    platform_key=None,
                    display_name=definition["display_name"],
                    target_ref=definition["target_ref"],
                    delivery_status=definition["status"],
                    ordinal=0,
                    metadata_json={},
                )
            )
        db.commit()

    due_at = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    for action_id in (2, 3, 4):
        accepted = client.post(
            f"/api/v1/workspaces/1/actions/{action_id}/accept",
            json={"assignee_user_id": 2, "due_at": due_at},
        )
        assert accepted.status_code == 200, accepted.text

    wrong_flow = client.post(
        "/api/v1/workspaces/1/actions/2/targets/2/transition",
        json={"to_status": "draft_write_requested", "idempotency_key": "wrong-article-flow"},
    )
    assert wrong_flow.status_code == 409

    _transition_target(client, 2, 2, "change_proposed", "official-01")
    _transition_target(client, 2, 2, "awaiting_brand_legal_review", "official-02")
    _approve_target(client, users, action_id=2, target_id=2, approval_type="brand_legal")
    _transition_target(client, 2, 2, "handed_to_web_owner", "official-03")
    _transition_target(client, 2, 2, "deployed", "official-04")
    _submit_target_evidence(
        client,
        action_id=2,
        target_id=2,
        evidence_type="same_domain_readback",
        source_url="https://example.com/product",
    )
    official = _transition_target(client, 2, 2, "same_domain_readback_verified", "official-05")

    _transition_target(client, 3, 3, "jsonld_proposed", "schema-01")
    _transition_target(client, 3, 3, "awaiting_technical_review", "schema-02")
    _approve_target(client, users, action_id=3, target_id=3, approval_type="technical")
    _transition_target(client, 3, 3, "deployed", "schema-03")
    _transition_target(client, 3, 3, "source_readback_verified", "schema-04")
    _submit_target_evidence(
        client,
        action_id=3,
        target_id=3,
        evidence_type="source_code",
        source_url="https://example.com/product",
    )
    missing_schema = client.post(
        "/api/v1/workspaces/1/actions/3/targets/3/transition",
        json={"to_status": "schema_validated", "idempotency_key": "schema-missing-validation"},
    )
    assert missing_schema.status_code == 409
    _submit_target_evidence(
        client,
        action_id=3,
        target_id=3,
        evidence_type="schema_validation",
        source_url="https://example.com/product",
    )
    structured = _transition_target(client, 3, 3, "schema_validated", "schema-05")

    _transition_target(client, 4, 4, "cooperation_briefed", "source-01")
    _transition_target(client, 4, 4, "external_execution", "source-02")
    _transition_target(client, 4, 4, "external_content_live", "source-03")
    wrong_source = client.post(
        "/api/v1/workspaces/1/actions/4/targets/4/evidence",
        json={
            "evidence_type": "external_publication",
            "source_url": "https://www.csdn.net/fake-proof",
            "detail": {},
            "idempotency_key": "wrong-third-party-domain",
        },
    )
    assert wrong_source.status_code == 201, wrong_source.text
    assert wrong_source.json()["verification_status"] == "rejected"
    assert "选定的第三方信源" in wrong_source.json()["detail"]["verification_reason"]
    _submit_target_evidence(
        client,
        action_id=4,
        target_id=4,
        evidence_type="external_publication",
        source_url="https://zhuanlan.zhihu.com/p/123456",
    )
    third_party = _transition_target(client, 4, 4, "public_readback_verified", "source-04")

    for completed in (official, structured, third_party):
        assert completed["stage"] == "ready_for_retest"
        assert completed["measurement_status"] == "eligible"
        assert completed["completed_target_count"] == 1
        assert completed["retest_eligible_target_count"] == 1
