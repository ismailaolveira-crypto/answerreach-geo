from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.api.deps import get_current_user
from app.db.session import Base, get_db
from app.main import create_app
from app.models import AuditLog
from app.models.company import Company
from app.models.cleanroom_v1 import (
    GeoActionOpportunity,
    GeoActionOpportunityEvidence,
    GeoActionEvent,
    GeoAgentArtifact,
    GeoAgentEvent,
    GeoContentAsset,
    GeoAgentRun,
    GeoBrandFact,
    GeoContentBrief,
    GeoContentClaim,
    GeoContentReview,
    GeoEvidence,
    GeoObservationRun,
    GeoOptimizationAction,
    GeoPlatformVariant,
    GeoQuestionPlan,
    GeoWorkspace,
)
from app.models.job import QueueJob
from app.models.user import User
from app.services.codex_agent_runtime import CodexRunTimedOut
from app.v1 import agent_orchestration, routes


@pytest.fixture
def review_client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    monkeypatch.setattr(
        routes,
        "verify_publication_page",
        lambda url: {
            "status": "publicly_verified",
            "verified_url": url,
            "status_code": 200,
            "content_type": "text/html",
            "sha256": "f" * 64,
            "size_bytes": 4096,
            "truncated": False,
            "redirect_count": 0,
            "verified_at": "2026-08-08T00:00:00+00:00",
        },
    )
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as db:
        db.add(Company(id=1, name="测试公司"))
        db.add(User(id=1, company_id=1, name="审核员", email="review@example.com", role="company_admin"))
        db.add(
            GeoWorkspace(
                id=1,
                company_id=1,
                slug="review-workspace",
                brand_name="测试品牌",
                brand_aliases=[],
                website_url="https://brand.example.com/",
            )
        )
        db.add(
            GeoOptimizationAction(
                id=1,
                workspace_id=1,
                title="补齐品牌答案",
                rationale="真实观测中缺失品牌答案",
                priority="high",
                status="in_progress",
                stage="reviewing",
            )
        )
        db.add(
            GeoContentBrief(
                id=1,
                workspace_id=1,
                action_id=1,
                audience="企业决策者",
                intent="答疑",
                asset_type="article",
                required_sections=[],
                brand_fact_ids=[],
                evidence_ids=[],
                source_urls=[],
                required_claims=[],
                forbidden_claims=[],
                open_questions=[],
                input_fingerprint="b" * 64,
                status="ready",
            )
        )
        db.add(
            GeoContentAsset(
                id=1,
                workspace_id=1,
                brief_id=1,
                version=1,
                title="平台选型稿",
                summary="用于真实审核门禁测试",
                body_markdown="# 平台选型稿",
                content_fingerprint="a" * 64,
                generation_usage={},
                status="draft",
            )
        )
        db.add_all(
            [
                GeoContentClaim(
                    id=1,
                    content_asset_id=1,
                    claim_key="source-claim",
                    claim_text="已有公开来源的事实",
                    support_type="public_source",
                    source_url="https://example.com/source",
                    verification_status="source_linked",
                ),
                GeoContentClaim(
                    id=2,
                    content_asset_id=1,
                    claim_key="brand-claim",
                    claim_text="需要审核员负责确认的品牌事实",
                    support_type="agent_pending",
                    verification_status="pending",
                ),
                GeoPlatformVariant(
                    id=1,
                    workspace_id=1,
                    content_asset_id=1,
                    platform_key="zhihu",
                    version=1,
                    policy_version="zhihu.v1",
                    title="知乎版标题",
                    summary="知乎版摘要",
                    body_markdown="知乎版正文",
                    tags=[],
                    image_manifest=[],
                    adaptation_contract={},
                    content_fingerprint="c" * 64,
                    status="ready",
                ),
                GeoPlatformVariant(
                    id=2,
                    workspace_id=1,
                    content_asset_id=1,
                    platform_key="wechat",
                    version=1,
                    policy_version="wechat.v1",
                    title="公众号版标题",
                    summary="公众号版摘要",
                    body_markdown="公众号版正文",
                    tags=[],
                    image_manifest=[],
                    adaptation_contract={},
                    content_fingerprint="d" * 64,
                    status="ready",
                ),
                GeoPlatformVariant(
                    id=3,
                    workspace_id=1,
                    content_asset_id=1,
                    platform_key="official_site",
                    version=1,
                    policy_version="official-site.v1",
                    title="官网版标题",
                    summary="官网版摘要",
                    body_markdown="官网版正文",
                    tags=[],
                    image_manifest=[],
                    adaptation_contract={},
                    content_fingerprint="e" * 64,
                    status="ready",
                ),
            ]
        )
        db.add(
            GeoAgentRun(
                id=1,
                workspace_id=1,
                action_id=1,
                runtime_key="local_codex",
                model="gpt-5-codex",
                codex_thread_id="thread-review-1",
                codex_turn_id="turn-review-1",
                status="awaiting_review",
                stage="awaiting_review",
                selected_platforms=["zhihu", "wechat"],
                request_snapshot={},
                result_snapshot={"asset_id": 1, "brief_id": 1},
            )
        )
        db.commit()

    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1, company_id=1, role="company_admin"
    )
    client = TestClient(app)
    client.app.state.review_session_factory = session_factory
    yield client
    app.dependency_overrides.clear()


def test_review_gate_and_browser_client_draft_readback(
    review_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = review_client.get("/api/v1/workspaces/1/content-assets/1/review-package")
    assert package.status_code == 200
    assert package.json()["pending_claim_count"] == 1
    blocked_review = review_client.post(
        "/api/v1/workspaces/1/content-assets/1/reviews",
        json={
            "verdict": "approved",
            "confirmed_claim_ids": [],
            "platform_keys": ["zhihu"],
            "reviewed_platform_keys": ["zhihu"],
        },
    )
    assert blocked_review.status_code == 422

    unreviewed_platform = review_client.post(
        "/api/v1/workspaces/1/content-assets/1/reviews",
        json={
            "verdict": "approved",
            "confirmed_claim_ids": [2],
            "platform_keys": ["zhihu"],
            "reviewed_platform_keys": [],
        },
    )
    assert unreviewed_platform.status_code == 422
    assert "请先打开并审阅" in unreviewed_platform.json()["detail"]

    approved = review_client.post(
        "/api/v1/workspaces/1/content-assets/1/reviews",
        json={
            "verdict": "approved",
            "confirmed_claim_ids": [2],
            "platform_keys": ["zhihu"],
            "reviewed_platform_keys": ["zhihu"],
            "note": "已与品牌负责人核对",
        },
    )
    assert approved.status_code == 201
    approved_payload = approved.json()
    assert approved_payload["approved_platform_keys"] == ["zhihu"]
    assert approved_payload["pending_claim_count"] == 0
    asset_review = next(
        review
        for review in approved_payload["reviews"]
        if review["subject_type"] == "content_asset"
    )
    assert asset_review["checks"]["reviewed_platform_keys"] == ["zhihu"]
    with review_client.app.state.review_session_factory() as db:
        variant_review = (
            db.query(GeoContentReview)
            .filter(GeoContentReview.subject_type == "platform_variant")
            .one()
        )
        assert variant_review.checks["reviewed_before_approval"] is True

    blocked_platform = review_client.post(
        "/api/v1/workspaces/1/distribution-runs",
        json={"content_asset_id": 1, "platform_keys": ["wechat"], "idempotency_key": "asset-1-wechat"},
    )
    assert blocked_platform.status_code == 409

    distribution = review_client.post(
        "/api/v1/workspaces/1/distribution-runs",
        json={"content_asset_id": 1, "platform_keys": ["zhihu"], "idempotency_key": "asset-1-zhihu"},
    )
    assert distribution.status_code == 201
    assert distribution.json()["stage"] == "ready_for_client"
    assert distribution.json()["targets"][0]["final_action_clicked"] is False
    run_id = distribution.json()["id"]

    missing_readback = review_client.post(
        f"/api/v1/workspaces/1/distribution-runs/{run_id}/client-results",
        json={"targets": [{"platform_key": "zhihu", "request_status": "draft_saved"}]},
    )
    assert missing_readback.status_code == 422

    persisted = review_client.post(
        f"/api/v1/workspaces/1/distribution-runs/{run_id}/client-results",
        json={
            "targets": [
                {
                    "platform_key": "zhihu",
                    "request_status": "draft_saved",
                    "draft_url": "https://www.zhihu.com/creator/manage/creation/draft/example",
                }
            ]
        },
    )
    assert persisted.status_code == 200
    assert persisted.json()["status"] == "draft_saved"
    assert persisted.json()["targets"][0]["draft_readback_status"] == "draft_saved"
    assert persisted.json()["targets"][0]["final_action_clicked"] is False
    assert persisted.json()["targets"][0]["human_publish_status"] == "awaiting_publish"

    target_id = persisted.json()["targets"][0]["id"]
    wrong_platform = review_client.post(
        f"/api/v1/workspaces/1/distribution-runs/{run_id}/targets/{target_id}/human-publication",
        json={"public_url": "https://example.com/articles/not-zhihu"},
    )
    assert wrong_platform.status_code == 422

    platform_homepage = review_client.post(
        f"/api/v1/workspaces/1/distribution-runs/{run_id}/targets/{target_id}/human-publication",
        json={"public_url": "https://www.zhihu.com/"},
    )
    assert platform_homepage.status_code == 422

    successful_verifier = routes.verify_publication_page

    def unavailable_page(_url: str) -> dict:
        from app.v1.website_audit import PublicationVerificationError

        raise PublicationVerificationError("public_page_request_failed")

    monkeypatch.setattr(routes, "verify_publication_page", unavailable_page)
    unreachable = review_client.post(
        f"/api/v1/workspaces/1/distribution-runs/{run_id}/targets/{target_id}/human-publication",
        json={"public_url": "https://zhuanlan.zhihu.com/p/123456789"},
    )
    assert unreachable.status_code == 409
    assert "不会记录" in unreachable.json()["detail"]
    monkeypatch.setattr(routes, "verify_publication_page", successful_verifier)

    published = review_client.post(
        f"/api/v1/workspaces/1/distribution-runs/{run_id}/targets/{target_id}/human-publication",
        json={"public_url": "https://zhuanlan.zhihu.com/p/123456789"},
    )
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    assert published.json()["targets"][0]["human_publish_status"] == "published"
    assert published.json()["targets"][0]["publication_verification_status"] == "publicly_verified"
    assert published.json()["targets"][0]["final_action_clicked"] is False

    corrected = review_client.post(
        f"/api/v1/workspaces/1/distribution-runs/{run_id}/targets/{target_id}/human-publication",
        json={"public_url": "https://www.zhihu.com/question/123/answer/456"},
    )
    assert corrected.status_code == 200
    assert corrected.json()["targets"][0]["public_url"].endswith("/answer/456")

    library = review_client.get("/api/v1/workspaces/1/content-library")
    assert library.status_code == 200
    assert len(library.json()) == 1
    assert library.json()[0]["approved_platform_keys"] == ["zhihu"]
    assert library.json()[0]["saved_draft_count"] == 1
    assert library.json()[0]["draft_targets"][0]["draft_url"].startswith("https://www.zhihu.com/")
    assert library.json()[0]["draft_targets"][0]["public_url"].endswith("/answer/456")


def test_platform_variant_can_be_edited_before_review_with_audit(
    review_client: TestClient,
) -> None:
    updated = review_client.patch(
        "/api/v1/workspaces/1/platform-variants/1",
        json={
            "title": "知乎人工修订标题",
            "summary": "审核员根据平台语气调整后的摘要",
            "body_markdown": "# 修订正文\n\n保留真实来源，删除未经核验的表述。",
            "tags": ["Token 管理", "GEO"],
            "category": "技术",
        },
    )

    assert updated.status_code == 200
    payload = updated.json()
    assert payload["title"] == "知乎人工修订标题"
    assert payload["body_markdown"].startswith("# 修订正文")
    assert payload["content_fingerprint"] != "c" * 64
    assert payload["adaptation_contract"]["manual_edit"]["editor_user_id"] == 1

    with review_client.app.state.review_session_factory() as db:
        event = db.query(GeoActionEvent).filter_by(
            event_type="platform_variant_edited"
        ).one()
        assert event.detail["variant_id"] == 1
        assert "body_markdown" not in event.detail


def test_platform_variant_edit_is_blocked_after_human_approval(
    review_client: TestClient,
) -> None:
    approved = review_client.post(
        "/api/v1/workspaces/1/content-assets/1/reviews",
        json={
            "verdict": "approved",
            "confirmed_claim_ids": [2],
            "platform_keys": ["zhihu"],
            "reviewed_platform_keys": ["zhihu"],
        },
    )
    assert approved.status_code == 201

    blocked = review_client.patch(
        "/api/v1/workspaces/1/platform-variants/1",
        json={
            "title": "不应写入",
            "summary": "审核后不应被覆盖",
            "body_markdown": "审核后不应被覆盖",
        },
    )
    assert blocked.status_code == 409


def test_browser_draft_link_requires_explicit_human_readback_confirmation(
    review_client: TestClient,
) -> None:
    approved = review_client.post(
        "/api/v1/workspaces/1/content-assets/1/reviews",
        json={
            "verdict": "approved",
            "confirmed_claim_ids": [2],
            "platform_keys": ["zhihu"],
            "reviewed_platform_keys": ["zhihu"],
        },
    )
    assert approved.status_code == 201
    created = review_client.post(
        "/api/v1/workspaces/1/distribution-runs",
        json={
            "content_asset_id": 1,
            "platform_keys": ["zhihu"],
            "idempotency_key": "asset-1-human-draft-readback",
        },
    )
    assert created.status_code == 201
    run_id = created.json()["id"]
    target_id = created.json()["targets"][0]["id"]

    wrong_domain = review_client.post(
        f"/api/v1/workspaces/1/distribution-runs/{run_id}/client-results",
        json={
            "targets": [
                {
                    "platform_key": "zhihu",
                    "request_status": "draft_link_returned",
                    "draft_url": "https://example.com/drafts/not-zhihu",
                }
            ]
        },
    )
    assert wrong_domain.status_code == 422

    returned = review_client.post(
        f"/api/v1/workspaces/1/distribution-runs/{run_id}/client-results",
        json={
            "targets": [
                {
                    "platform_key": "zhihu",
                    "request_status": "draft_link_returned",
                    "draft_url": "https://www.zhihu.com/creator/manage/creation/draft/human-check",
                }
            ]
        },
    )
    assert returned.status_code == 200
    payload = returned.json()
    assert payload["status"] == "pending"
    assert payload["stage"] == "awaiting_readback"
    target = payload["targets"][0]
    assert target["request_status"] == "draft_link_returned"
    assert target["draft_readback_status"] == "awaiting_human_confirmation"
    assert target["candidate_draft_url"].endswith("/human-check")
    assert target["draft_url"] is None
    assert target["human_publish_status"] == "not_ready"
    assert target["final_action_clicked"] is False

    premature_publication = review_client.post(
        f"/api/v1/workspaces/1/distribution-runs/{run_id}/targets/{target_id}/human-publication",
        json={"public_url": "https://zhuanlan.zhihu.com/p/123456789"},
    )
    assert premature_publication.status_code == 409
    rejected_assertion = review_client.post(
        f"/api/v1/workspaces/1/distribution-runs/{run_id}/targets/{target_id}/human-draft-readback",
        json={"confirmed_visible": False},
    )
    assert rejected_assertion.status_code == 422

    confirmed = review_client.post(
        f"/api/v1/workspaces/1/distribution-runs/{run_id}/targets/{target_id}/human-draft-readback",
        json={"confirmed_visible": True},
    )
    assert confirmed.status_code == 200
    payload = confirmed.json()
    assert payload["status"] == "draft_saved"
    assert payload["stage"] == "draft_saved"
    target = payload["targets"][0]
    assert target["request_status"] == "draft_saved"
    assert target["draft_readback_status"] == "draft_saved"
    assert target["draft_url"].endswith("/human-check")
    assert target["readback_artifact_uri"].startswith("human://draft-readback/")
    assert target["human_publish_status"] == "awaiting_publish"
    assert target["final_action_clicked"] is False

    repeated = review_client.post(
        f"/api/v1/workspaces/1/distribution-runs/{run_id}/targets/{target_id}/human-draft-readback",
        json={"confirmed_visible": True},
    )
    assert repeated.status_code == 200
    assert repeated.json()["targets"][0]["draft_readback_status"] == "draft_saved"


def test_four_technical_platforms_create_distinct_reviewable_drafts(
    review_client: TestClient,
) -> None:
    created = review_client.post(
        "/api/v1/workspaces/1/actions/1/briefs/1/assets/1/variants",
        json={"platform_keys": ["zhihu", "juejin", "csdn", "51cto"]},
    )
    assert created.status_code == 201
    variants = {item["platform_key"]: item for item in created.json()}
    assert set(variants) == {"zhihu", "juejin", "csdn", "51cto"}
    technical_labels = {
        variants[key]["adaptation_contract"]["label"]
        for key in {"juejin", "csdn", "51cto"}
    }
    assert technical_labels == {
        "稀土掘金",
        "CSDN",
        "51CTO",
    }
    assert len({variants[key]["body_markdown"] for key in variants}) == 4

    approved = review_client.post(
        "/api/v1/workspaces/1/content-assets/1/reviews",
        json={
            "verdict": "approved",
            "confirmed_claim_ids": [2],
            "platform_keys": ["zhihu", "juejin", "csdn", "51cto"],
            "reviewed_platform_keys": ["zhihu", "juejin", "csdn", "51cto"],
        },
    )
    assert approved.status_code == 201
    assert set(approved.json()["approved_platform_keys"]) == {
        "zhihu",
        "juejin",
        "csdn",
        "51cto",
    }

    distribution = review_client.post(
        "/api/v1/workspaces/1/distribution-runs",
        json={
            "content_asset_id": 1,
            "platform_keys": ["zhihu", "juejin", "csdn", "51cto"],
            "idempotency_key": "asset-1-four-technical-platforms",
        },
    )
    assert distribution.status_code == 201
    assert distribution.json()["stage"] == "ready_for_client"
    assert {target["platform_key"] for target in distribution.json()["targets"]} == {
        "zhihu",
        "juejin",
        "csdn",
        "51cto",
    }
    assert all(target["final_action_clicked"] is False for target in distribution.json()["targets"])


@pytest.mark.parametrize(
    ("platform_key", "public_url"),
    [
        ("zhihu", "https://zhuanlan.zhihu.com/p/123456"),
        ("juejin", "https://juejin.cn/post/123456"),
        ("csdn", "https://blog.csdn.net/example/article/details/123456"),
        ("51cto", "https://blog.51cto.com/example/123456"),
    ],
)
def test_four_technical_platform_publication_urls_are_scoped(
    platform_key: str,
    public_url: str,
) -> None:
    workspace = SimpleNamespace(website_url="https://brand.example.com/")
    assert routes._validated_publication_url(workspace, platform_key, public_url) == public_url


def test_agent_result_requires_rule_sources_and_variants_for_every_platform() -> None:
    run = SimpleNamespace(selected_platforms=["zhihu", "juejin"])
    incomplete = {
        "platform_research": [
            {
                "platform_key": "zhihu",
                "tone": "克制",
                "restrictions": ["禁止硬广"],
                "source_urls": ["https://www.zhihu.com/term/zhihu-terms"],
            }
        ],
        "variants": [
            {
                "platform_key": "zhihu",
                "title": "标题",
                "summary": "摘要",
                "body_markdown": "正文",
            }
        ],
    }
    with pytest.raises(ValueError, match="platform research is incomplete"):
        agent_orchestration._validate_agent_result(run, incomplete)


def test_action_workbench_state_returns_persisted_flow_without_empty_retest_errors(
    review_client: TestClient,
) -> None:
    response = review_client.get("/api/v1/workspaces/1/action-workbench-state")

    assert response.status_code == 200
    payload = response.json()
    assert [run["id"] for run in payload["agent_runs"]] == [1]
    assert [package["asset"]["id"] for package in payload["review_packages"]] == [1]
    assert payload["review_packages"][0]["pending_claim_count"] == 1
    assert payload["distribution_runs"] == []
    assert payload["retests"] == []


def test_review_rejects_draft_that_ignored_available_sourced_brand_facts(
    review_client: TestClient,
) -> None:
    with review_client.app.state.review_session_factory() as db:
        fact = GeoBrandFact(
            workspace_id=1,
            title="产品定位",
            statement="测试品牌是企业大模型统一管理平台。",
            source_url="https://brand.example.com/product",
            status="active",
        )
        db.add(fact)
        db.flush()
        db.add(
            AuditLog(
                actor_user_id=1,
                actor_role="company_admin",
                action="workspace.brand_fact.source_verified",
                resource_type="geo_brand_fact",
                resource_id=fact.id,
                company_id=1,
                detail_json={
                    "workspace_id": 1,
                    "source_url": fact.source_url,
                    "statement_sha256": sha256(fact.statement.encode("utf-8")).hexdigest(),
                    "verification": {
                        "status": "source_and_statement_verified",
                        "verified_url": fact.source_url,
                        "statement_sha256": sha256(fact.statement.encode("utf-8")).hexdigest(),
                    },
                },
            )
        )
        db.commit()

    package = review_client.get("/api/v1/workspaces/1/content-assets/1/review-package")
    assert package.status_code == 200
    assert package.json()["available_sourced_brand_fact_count"] == 1
    assert package.json()["sourced_brand_fact_count"] == 0

    library = review_client.get("/api/v1/workspaces/1/content-library")
    assert library.status_code == 200
    assert library.json()[0]["available_sourced_brand_fact_count"] == 1
    assert library.json()[0]["sourced_brand_fact_count"] == 0
    assert library.json()[0]["brand_fact_snapshot_stale"] is True

    blocked = review_client.post(
        "/api/v1/workspaces/1/content-assets/1/reviews",
        json={
            "verdict": "approved",
            "confirmed_claim_ids": [2],
            "platform_keys": ["zhihu"],
            "reviewed_platform_keys": ["zhihu"],
        },
    )
    assert blocked.status_code == 409
    assert "这版稿件未使用任何一条" in blocked.json()["detail"]

    returned = review_client.post(
        "/api/v1/workspaces/1/content-assets/1/reviews",
        json={
            "verdict": "changes_requested",
            "note": "请使用当前带来源的品牌事实重新生成。",
        },
    )
    assert returned.status_code == 201
    assert returned.json()["asset"]["status"] == "changes_requested"


def test_review_can_keep_unknown_claim_unverified_without_false_confirmation(
    review_client: TestClient,
) -> None:
    conflicting = review_client.post(
        "/api/v1/workspaces/1/content-assets/1/reviews",
        json={
            "verdict": "approved",
            "confirmed_claim_ids": [2],
            "unverified_claim_ids": [2],
            "platform_keys": ["zhihu"],
            "reviewed_platform_keys": ["zhihu"],
        },
    )
    assert conflicting.status_code == 422

    approved = review_client.post(
        "/api/v1/workspaces/1/content-assets/1/reviews",
        json={
            "verdict": "approved",
            "confirmed_claim_ids": [],
            "unverified_claim_ids": [2],
            "platform_keys": ["zhihu", "wechat"],
            "reviewed_platform_keys": ["zhihu", "wechat"],
            "note": "稿件明确将该能力保留为待核验，不作为产品事实使用",
        },
    )
    assert approved.status_code == 201
    payload = approved.json()
    assert payload["approved_platform_keys"] == ["wechat", "zhihu"]
    assert payload["pending_claim_count"] == 0
    pending_claim = next(claim for claim in payload["claims"] if claim["id"] == 2)
    assert pending_claim["verification_status"] == "explicitly_unverified"
    assert "不得将其作为已证实事实" in pending_claim["review_note"]
    asset_review = next(
        review
        for review in payload["reviews"]
        if review["subject_type"] == "content_asset"
    )
    assert asset_review["checks"]["confirmed_claim_ids"] == []
    assert asset_review["checks"]["unverified_claim_ids"] == [2]

    distribution = review_client.post(
        "/api/v1/workspaces/1/distribution-runs",
        json={
            "content_asset_id": 1,
            "platform_keys": ["zhihu", "wechat"],
            "idempotency_key": "asset-1-explicitly-unverified",
        },
    )
    assert distribution.status_code == 201
    assert distribution.json()["stage"] == "ready_for_client"
    assert {target["platform_key"] for target in distribution.json()["targets"]} == {
        "zhihu",
        "wechat",
    }


def test_two_platform_draft_results_can_be_archived_sequentially_and_retried(
    review_client: TestClient,
) -> None:
    approved = review_client.post(
        "/api/v1/workspaces/1/content-assets/1/reviews",
        json={
            "verdict": "approved",
            "confirmed_claim_ids": [2],
            "platform_keys": ["zhihu", "wechat"],
            "reviewed_platform_keys": ["zhihu", "wechat"],
        },
    )
    assert approved.status_code == 201

    created = review_client.post(
        "/api/v1/workspaces/1/distribution-runs",
        json={
            "content_asset_id": 1,
            "platform_keys": ["zhihu", "wechat"],
            "idempotency_key": "asset-1-sequential-two-platforms",
        },
    )
    assert created.status_code == 201
    run_id = created.json()["id"]

    first = review_client.post(
        f"/api/v1/workspaces/1/distribution-runs/{run_id}/client-results",
        json={
            "targets": [
                {
                    "platform_key": "zhihu",
                    "request_status": "draft_saved",
                    "draft_url": "https://www.zhihu.com/creator/manage/creation/draft/one",
                }
            ]
        },
    )
    assert first.status_code == 200
    assert first.json()["status"] == "partial"
    by_platform = {target["platform_key"]: target for target in first.json()["targets"]}
    assert by_platform["zhihu"]["draft_readback_status"] == "draft_saved"
    assert by_platform["wechat"]["draft_readback_status"] == "not_started"
    assert all(target["final_action_clicked"] is False for target in first.json()["targets"])

    second = review_client.post(
        f"/api/v1/workspaces/1/distribution-runs/{run_id}/client-results",
        json={
            "targets": [
                {
                    "platform_key": "wechat",
                    "request_status": "failed",
                    "message": "公众号登录已失效",
                }
            ]
        },
    )
    assert second.status_code == 200
    assert second.json()["status"] == "partial"

    retry = review_client.post(
        f"/api/v1/workspaces/1/distribution-runs/{run_id}/client-results",
        json={
            "targets": [
                {
                    "platform_key": "wechat",
                    "request_status": "draft_saved",
                    "external_draft_id": "wechat-draft-1",
                }
            ]
        },
    )
    assert retry.status_code == 200
    assert retry.json()["status"] == "draft_saved"
    assert all(
        target["draft_readback_status"] == "draft_saved"
        and target["final_action_clicked"] is False
        for target in retry.json()["targets"]
    )


def test_later_platform_login_extends_the_same_distribution_run(
    review_client: TestClient,
) -> None:
    approved = review_client.post(
        "/api/v1/workspaces/1/content-assets/1/reviews",
        json={
            "verdict": "approved",
            "confirmed_claim_ids": [2],
            "platform_keys": ["zhihu", "wechat"],
            "reviewed_platform_keys": ["zhihu", "wechat"],
        },
    )
    assert approved.status_code == 201

    first = review_client.post(
        "/api/v1/workspaces/1/distribution-runs",
        json={
            "content_asset_id": 1,
            "platform_keys": ["zhihu"],
            "idempotency_key": "asset-1-first-login-zhihu",
        },
    )
    assert first.status_code == 201
    run_id = first.json()["id"]
    zhihu_saved = review_client.post(
        f"/api/v1/workspaces/1/distribution-runs/{run_id}/client-results",
        json={
            "targets": [
                {
                    "platform_key": "zhihu",
                    "request_status": "draft_saved",
                    "draft_url": "https://www.zhihu.com/creator/manage/creation/draft/later-login",
                }
            ]
        },
    )
    assert zhihu_saved.status_code == 200
    assert zhihu_saved.json()["status"] == "draft_saved"

    extended = review_client.post(
        "/api/v1/workspaces/1/distribution-runs",
        json={
            "content_asset_id": 1,
            "platform_keys": ["zhihu", "wechat"],
            "idempotency_key": "asset-1-later-login-both",
        },
    )
    assert extended.status_code == 201
    payload = extended.json()
    assert payload["id"] == run_id
    assert payload["requested_platforms"] == ["zhihu", "wechat"]
    assert payload["status"] == "partial"
    by_platform = {target["platform_key"]: target for target in payload["targets"]}
    assert by_platform["zhihu"]["draft_readback_status"] == "draft_saved"
    assert by_platform["wechat"]["draft_readback_status"] == "not_started"

    completed = review_client.post(
        f"/api/v1/workspaces/1/distribution-runs/{run_id}/client-results",
        json={
            "targets": [
                {
                    "platform_key": "wechat",
                    "request_status": "draft_saved",
                    "external_draft_id": "wechat-later-login-draft",
                }
            ]
        },
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "draft_saved"
    assert all(
        target["draft_readback_status"] == "draft_saved"
        for target in completed.json()["targets"]
    )

    library = review_client.get("/api/v1/workspaces/1/content-library")
    assert library.status_code == 200
    assert library.json()[0]["distribution_run_id"] == run_id
    assert library.json()[0]["saved_draft_count"] == 2
    assert library.json()[0]["total_draft_targets"] == 2
    runs = review_client.get("/api/v1/workspaces/1/distribution-runs")
    assert runs.status_code == 200
    assert [run["id"] for run in runs.json()] == [run_id]


def test_official_site_uses_manual_handoff_before_human_publication(
    review_client: TestClient,
) -> None:
    approved = review_client.post(
        "/api/v1/workspaces/1/content-assets/1/reviews",
        json={
            "verdict": "approved",
            "confirmed_claim_ids": [2],
            "platform_keys": ["official_site"],
            "reviewed_platform_keys": ["official_site"],
        },
    )
    assert approved.status_code == 201

    mixed = review_client.post(
        "/api/v1/workspaces/1/distribution-runs",
        json={
            "content_asset_id": 1,
            "platform_keys": ["official_site", "zhihu"],
            "idempotency_key": "asset-1-mixed-website",
        },
    )
    assert mixed.status_code == 422

    created = review_client.post(
        "/api/v1/workspaces/1/distribution-runs",
        json={
            "content_asset_id": 1,
            "platform_keys": ["official_site"],
            "idempotency_key": "asset-1-official-site-handoff",
        },
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["stage"] == "awaiting_publication"
    assert payload["status"] == "awaiting_publication"
    assert payload["targets"][0]["adapter_version"] == "manual-website.v1"
    assert payload["targets"][0]["request_status"] == "handoff_ready"
    assert payload["targets"][0]["draft_readback_status"] == "not_required"
    assert payload["targets"][0]["human_publish_status"] == "awaiting_publish"
    assert payload["targets"][0]["final_action_clicked"] is False

    duplicate = review_client.post(
        "/api/v1/workspaces/1/distribution-runs",
        json={
            "content_asset_id": 1,
            "platform_keys": ["official_site"],
            "idempotency_key": "asset-1-official-site-handoff",
        },
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == payload["id"]

    rejected_sync_result = review_client.post(
        f"/api/v1/workspaces/1/distribution-runs/{payload['id']}/client-results",
        json={
            "targets": [
                {
                    "platform_key": "official_site",
                    "request_status": "draft_saved",
                    "draft_url": "https://brand.example.com/preview",
                }
            ]
        },
    )
    assert rejected_sync_result.status_code == 409

    target_id = payload["targets"][0]["id"]
    wrong_domain = review_client.post(
        f"/api/v1/workspaces/1/distribution-runs/{payload['id']}/targets/{target_id}/human-publication",
        json={"public_url": "https://example.net/product"},
    )
    assert wrong_domain.status_code == 422

    published = review_client.post(
        f"/api/v1/workspaces/1/distribution-runs/{payload['id']}/targets/{target_id}/human-publication",
        json={"public_url": "https://brand.example.com/"},
    )
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    assert published.json()["targets"][0]["public_url"] == "https://brand.example.com/"
    assert published.json()["targets"][0]["publication_verification_status"] == "publicly_verified"
    assert published.json()["targets"][0]["final_action_clicked"] is False

    library = review_client.get("/api/v1/workspaces/1/content-library")
    assert library.status_code == 200
    assert library.json()[0]["saved_draft_count"] == 0
    assert library.json()[0]["draft_targets"][0]["adapter_version"] == "manual-website.v1"

    session_factory = review_client.app.state.review_session_factory
    with session_factory() as db:
        action = db.get(GeoOptimizationAction, 1)
        assert action is not None
        assert action.stage == "ready_for_retest"


def test_agent_progress_is_derived_from_persisted_events_without_local_paths(
    review_client: TestClient,
) -> None:
    session_factory = review_client.app.state.review_session_factory
    with session_factory() as db:
        db.add_all(
            [
                GeoAgentEvent(workspace_id=1, agent_run_id=1, sequence=1, event_type="stage_started", stage="preparing_context", message="正在整理真实证据", detail={}),
                GeoAgentEvent(workspace_id=1, agent_run_id=1, sequence=2, event_type="stage_started", stage="researching_platform", message="正在查阅平台规则", detail={}),
                GeoAgentEvent(workspace_id=1, agent_run_id=1, sequence=3, event_type="stage_completed", stage="researching_brand", message="品牌事实已核对", detail={}),
                GeoAgentEvent(workspace_id=1, agent_run_id=1, sequence=4, event_type="stage_completed", stage="adapting_platforms", message="平台稿已生成", detail={}),
                GeoAgentEvent(workspace_id=1, agent_run_id=1, sequence=5, event_type="awaiting_human_review", stage="awaiting_review", message="等待人工审核", detail={}),
                GeoAgentArtifact(
                    workspace_id=1,
                    agent_run_id=1,
                    artifact_kind="structured_result",
                    uri="/private/agent-runs/1/result.json",
                    sha256="e" * 64,
                    size_bytes=128,
                    metadata_json={"private": "not-for-product-ui"},
                ),
            ]
        )
        db.commit()

    response = review_client.get("/api/v1/workspaces/1/agent-runs/1/progress")
    assert response.status_code == 200
    payload = response.json()
    assert payload["progress_percent"] == 100
    assert [stage["state"] for stage in payload["stages"]] == [
        "done",
        "done",
        "done",
        "done",
        "waiting_human",
    ]
    assert payload["event_count"] == 5
    assert payload["artifacts"][0]["artifact_kind"] == "structured_result"
    assert "uri" not in payload["artifacts"][0]
    assert "metadata_json" not in payload["artifacts"][0]


def test_agent_progress_scopes_timing_and_artifacts_to_latest_attempt(
    review_client: TestClient,
) -> None:
    now = datetime.now(timezone.utc)
    first_started_at = now - timedelta(minutes=30)
    latest_started_at = now - timedelta(seconds=8)
    session_factory = review_client.app.state.review_session_factory
    with session_factory() as db:
        run = db.get(GeoAgentRun, 1)
        assert run is not None
        run.status = "running"
        run.stage = "researching_platform"
        run.started_at = first_started_at
        run.finished_at = None
        db.add_all(
            [
                GeoAgentEvent(workspace_id=1, agent_run_id=1, sequence=1, event_type="run_queued", stage="queued", message="首次入队", detail={}, created_at=first_started_at),
                GeoAgentEvent(workspace_id=1, agent_run_id=1, sequence=2, event_type="stage_started", stage="preparing_context", message="首次执行", detail={}, created_at=first_started_at),
                GeoAgentEvent(workspace_id=1, agent_run_id=1, sequence=3, event_type="revision_queued", stage="queued", message="修订入队", detail={}, created_at=latest_started_at),
                GeoAgentEvent(workspace_id=1, agent_run_id=1, sequence=4, event_type="stage_started", stage="preparing_context", message="开始修订", detail={}, created_at=latest_started_at),
                GeoAgentEvent(workspace_id=1, agent_run_id=1, sequence=5, event_type="stage_started", stage="researching_platform", message="修订中", detail={}, created_at=latest_started_at),
                GeoAgentArtifact(workspace_id=1, agent_run_id=1, artifact_kind="structured_result", uri="/private/agent-runs/1/old.json", sha256="a" * 64, size_bytes=64, metadata_json={}, created_at=first_started_at),
                GeoAgentArtifact(workspace_id=1, agent_run_id=1, artifact_kind="structured_result", uri="/private/agent-runs/1/current.json", sha256="b" * 64, size_bytes=96, metadata_json={}, created_at=latest_started_at + timedelta(seconds=1)),
            ]
        )
        db.commit()

    response = review_client.get("/api/v1/workspaces/1/agent-runs/1/progress")
    assert response.status_code == 200
    payload = response.json()
    assert payload["attempt_number"] == 2
    assert payload["attempt_event_count"] == 3
    assert payload["event_count"] == 5
    assert 7 <= payload["elapsed_seconds"] <= 20
    assert payload["timeout_remaining_seconds"] == payload["timeout_seconds"] - payload["elapsed_seconds"]
    assert [artifact["sha256"] for artifact in payload["artifacts"]] == ["b" * 64]


def test_rejected_asset_can_resume_original_agent_thread_for_a_new_version(
    review_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rejected = review_client.post(
        "/api/v1/workspaces/1/content-assets/1/reviews",
        json={
            "verdict": "changes_requested",
            "confirmed_claim_ids": [],
            "platform_keys": ["zhihu", "wechat"],
            "note": "删除没有来源的客户数量，并补充私有化部署的适用边界。",
        },
    )
    assert rejected.status_code == 201
    assert rejected.json()["asset"]["status"] == "changes_requested"

    blocked_reapproval = review_client.post(
        "/api/v1/workspaces/1/content-assets/1/reviews",
        json={
            "verdict": "approved",
            "confirmed_claim_ids": [2],
            "platform_keys": ["zhihu"],
            "reviewed_platform_keys": ["zhihu"],
        },
    )
    assert blocked_reapproval.status_code == 409

    library = review_client.get("/api/v1/workspaces/1/content-library")
    assert library.status_code == 200
    assert library.json()[0]["latest_review_verdict"] == "changes_requested"
    assert "私有化部署" in library.json()[0]["latest_review_note"]

    revision = review_client.post(
        "/api/v1/workspaces/1/agent-runs/1/revise",
        json={"content_asset_id": 1},
    )
    assert revision.status_code == 202
    assert revision.json()["status"] == "resuming"
    assert revision.json()["stage"] == "queued"

    class RevisionRuntime:
        def run_structured(self, **kwargs):
            assert "删除没有来源的客户数量" in kwargs["prompt"]
            assert kwargs["thread_id"] == "thread-review-1"
            kwargs["on_started"]("thread-review-1", "turn-review-2")
            result = {
                "platform_research": [
                    {
                        "platform_key": key,
                        "tone": "理性、可核验",
                        "restrictions": ["不使用无来源数据"],
                        "source_urls": ["https://example.com/rules"],
                    }
                    for key in ["zhihu", "wechat"]
                ],
                "brand_research": {"verified_facts": [], "unknowns": ["客户数量"]},
                "master": {
                    "title": "平台选型稿（修订版）",
                    "summary": "删除了无来源数据，补充适用边界。",
                    "body_markdown": "# 修订版\n\n本文仅说明可核验边界。",
                    "claims": [
                        {
                            "text": "当前无公开客户数量可供核验。",
                            "source_url": None,
                            "verification_status": "pending",
                        }
                    ],
                },
                "variants": [
                    {
                        "platform_key": key,
                        "title": f"{key} 修订版",
                        "summary": "平台适配后的修订内容",
                        "body_markdown": f"# {key}\n\n修订后的完整内容。",
                        "tags": ["私有化"],
                        "adaptation_notes": ["已按人工意见删除无来源数据"],
                    }
                    for key in ["zhihu", "wechat"]
                ],
            }
            return SimpleNamespace(
                final_response=json.dumps(result, ensure_ascii=False),
                usage={"input_tokens": 120, "output_tokens": 80},
                runtime_events=[],
                thread_id="thread-review-1",
                turn_id="turn-review-2",
            )

    monkeypatch.setattr(agent_orchestration, "ARTIFACT_ROOT", tmp_path / "agent-runs")
    session_factory = review_client.app.state.review_session_factory
    with session_factory() as db:
        run = db.get(GeoAgentRun, 1)
        completed = agent_orchestration.execute_agent_run(db, run, runtime=RevisionRuntime())
        assert completed.status == "awaiting_review"
        assert completed.result_snapshot["asset_id"] != 1
        old_asset = db.get(GeoContentAsset, 1)
        new_asset = db.get(GeoContentAsset, completed.result_snapshot["asset_id"])
        assert old_asset.status == "superseded"
        assert new_asset.version == 2
        assert new_asset.generation_usage["revision_of_asset_id"] == 1

    duplicate = review_client.post(
        "/api/v1/workspaces/1/agent-runs/1/revise",
        json={"content_asset_id": 1},
    )
    assert duplicate.status_code == 409

    library = review_client.get("/api/v1/workspaces/1/content-library")
    assert library.status_code == 200
    library_by_id = {item["asset"]["id"]: item for item in library.json()}
    assert library_by_id[new_asset.id]["is_latest_version"] is True
    assert library_by_id[1]["is_latest_version"] is False
    assert library_by_id[1]["latest_version_id"] == new_asset.id
    assert library_by_id[1]["latest_version_number"] == 2


def test_agent_capacity_and_pending_job_cancellation_are_truthful(
    review_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = review_client.app.state.review_session_factory
    with session_factory() as db:
        question = GeoQuestionPlan(
            id=1,
            workspace_id=1,
            question_text="企业如何评估 Token 统一管控平台？",
            status="active",
            active=True,
        )
        observation_run = GeoObservationRun(
            id=1,
            workspace_id=1,
            adapter_key="test-official-search",
            status="completed",
        )
        db.add_all([question, observation_run])
        db.flush()
        evidence = GeoEvidence(
            id=1,
            workspace_id=1,
            run_id=observation_run.id,
            question_plan_id=question.id,
            model_key="qwen",
            model_label="通义千问",
            sample_mode="official_api",
            evidence_level="auditable",
            collection_method="official_api_web_search",
            evidence_kind="answer",
            is_real_provider_evidence=True,
            brand_status="absent",
            answer_text="真实联网回答未提及品牌。",
            answer_hash=sha256(b"capacity-evidence").hexdigest(),
            source_items=[{"title": "公开来源", "url": "https://example.com/source"}],
            sampling_environment={"search_verified": True, "search_event_count": 1},
            raw_artifact_uri="file:///tmp/capacity-evidence.json",
            captured_at=datetime.now(timezone.utc),
        )
        db.add(evidence)
        db.flush()
        opportunity = GeoActionOpportunity(
            id=1,
            workspace_id=1,
            fingerprint=sha256(b"capacity-opportunity").hexdigest(),
            opportunity_type="brand_absent",
            title="补齐品牌答案",
            summary="由完整真实观测证据生成。",
            priority_score=90,
            priority_label="high",
            evidence_strength=1,
            recommended_asset_type="article",
            recommended_platforms=["zhihu", "wechat"],
            status="open",
        )
        db.add(opportunity)
        db.flush()
        db.add(
            GeoActionOpportunityEvidence(
                id=1,
                opportunity_id=opportunity.id,
                workspace_id=1,
                evidence_id=evidence.id,
                question_plan_id=question.id,
                model_key="qwen",
                signal_type="brand_absent",
                signal_value={"brand_status": "absent"},
                evidence_hash=evidence.answer_hash,
                source_url="https://example.com/source",
            )
        )
        db.add_all(
            [
                GeoOptimizationAction(
                    id=2,
                    workspace_id=1,
                    question_plan_id=question.id,
                    source_evidence_id=evidence.id,
                    opportunity_id=opportunity.id,
                    title="第二个行动",
                    rationale="验证容量限制",
                    priority="high",
                    status="in_progress",
                    stage="selected",
                ),
                GeoOptimizationAction(
                    id=3,
                    workspace_id=1,
                    question_plan_id=question.id,
                    source_evidence_id=evidence.id,
                    opportunity_id=opportunity.id,
                    title="第三个行动",
                    rationale="验证容量释放",
                    priority="medium",
                    status="in_progress",
                    stage="selected",
                ),
            ]
        )
        db.commit()

    monkeypatch.setattr(
        routes,
        "diagnose_local_codex",
        lambda: {
            "runtime_key": "local_codex",
            "sdk_installed": True,
            "sdk_version": "test",
            "runtime_version": "Codex Desktop/test",
            "ready": True,
            "login_status": "chatgpt_authenticated",
            "default_model": "gpt-5-codex",
            "available_models": ["gpt-5-codex"],
            "error": None,
        },
    )

    queued = review_client.post(
        "/api/v1/workspaces/1/actions/2/agent-runs",
        json={"selected_platforms": ["zhihu", "wechat"]},
    )
    assert queued.status_code == 202
    run_id = queued.json()["id"]
    job_id = queued.json()["job_id"]

    runtime = review_client.get("/api/v1/workspaces/1/agent-runtime")
    assert runtime.status_code == 200
    assert runtime.json()["active_run_count"] == 1
    assert runtime.json()["max_concurrent_runs"] == 10
    assert runtime.json()["capacity_available"] is True
    assert runtime.json()["run_timeout_seconds"] == 900

    second = review_client.post(
        "/api/v1/workspaces/1/actions/3/agent-runs",
        json={"selected_platforms": ["zhihu"]},
    )
    assert second.status_code == 202
    second_cleanup = review_client.post(
        f"/api/v1/workspaces/1/agent-runs/{second.json()['id']}/interrupt"
    )
    assert second_cleanup.status_code == 200

    cancelled = review_client.post(f"/api/v1/workspaces/1/agent-runs/{run_id}/interrupt")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["stage"] == "cancelled"

    with session_factory() as db:
        job = db.get(QueueJob, job_id)
        action = db.get(GeoOptimizationAction, 2)
        assert job.status == "success"
        assert job.payload_json["cancelled_before_start"] is True
        assert action.stage == "selected"

    released = review_client.get("/api/v1/workspaces/1/agent-runtime")
    assert released.json()["active_run_count"] == 0
    assert released.json()["capacity_available"] is True

    next_run = review_client.post(
        "/api/v1/workspaces/1/actions/3/agent-runs",
        json={"selected_platforms": ["wechat"]},
    )
    assert next_run.status_code == 202
    cleanup = review_client.post(
        f"/api/v1/workspaces/1/agent-runs/{next_run.json()['id']}/interrupt"
    )
    assert cleanup.status_code == 200
    assert cleanup.json()["status"] == "cancelled"


def test_agent_capacity_allows_ten_and_blocks_the_eleventh(
    review_client: TestClient,
) -> None:
    session_factory = review_client.app.state.review_session_factory
    with session_factory() as db:
        db.add_all(
            [
                GeoAgentRun(
                    id=100 + index,
                    workspace_id=1,
                    action_id=1,
                    status="running",
                    stage="researching",
                    selected_platforms=["zhihu"],
                    request_snapshot={},
                    result_snapshot={},
                )
                for index in range(10)
            ]
        )
        db.commit()

        limit, active = routes._agent_capacity(db, 1)
        assert limit == 10
        assert len(active) == 10
        with pytest.raises(HTTPException) as blocked:
            routes._assert_agent_capacity(db, 1)
        assert blocked.value.status_code == 409
        assert "10/10" in str(blocked.value.detail)

        db.get(GeoAgentRun, 100).status = "completed"
        db.commit()
        routes._assert_agent_capacity(db, 1)


def test_worker_honors_cancellation_won_during_queue_handoff(review_client: TestClient) -> None:
    session_factory = review_client.app.state.review_session_factory
    with session_factory() as db:
        run = db.get(GeoAgentRun, 1)
        action = db.get(GeoOptimizationAction, 1)
        run.status = "cancelling"
        run.stage = "queued"
        action.stage = "generating"
        db.commit()

        result = agent_orchestration.execute_agent_run(db, run)
        assert result.status == "cancelled"
        assert result.stage == "cancelled"
        assert action.stage == "reviewing"


def test_visual_artifact_content_is_scoped_and_integrity_checked(
    review_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "agent-runs"
    screenshot = root / "1" / "1" / "visuals" / "official-page-1.png"
    screenshot.parent.mkdir(parents=True)
    payload = b"\x89PNG\r\n\x1a\nverified-visual"
    screenshot.write_bytes(payload)
    session_factory = review_client.app.state.review_session_factory
    with session_factory() as db:
        db.add(
            GeoAgentArtifact(
                id=1,
                workspace_id=1,
                agent_run_id=1,
                artifact_kind="official_page_screenshot",
                uri=str(screenshot),
                sha256=sha256(payload).hexdigest(),
                size_bytes=len(payload),
                metadata_json={"media_type": "image/png"},
            )
        )
        db.commit()
    monkeypatch.setattr(routes, "AGENT_ARTIFACT_ROOT", root)

    response = review_client.get("/api/v1/workspaces/1/agent-artifacts/1/content")
    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, max-age=3600"

    screenshot.write_bytes(b"tampered")
    tampered = review_client.get("/api/v1/workspaces/1/agent-artifacts/1/content")
    assert tampered.status_code == 409


def test_agent_timeout_is_persisted_as_a_recoverable_failure(review_client: TestClient) -> None:
    class TimeoutRuntime:
        def run_structured(self, **kwargs):
            assert kwargs["timeout_seconds"] == 900
            raise CodexRunTimedOut("Codex turn exceeded 900 seconds")

    session_factory = review_client.app.state.review_session_factory
    with session_factory() as db:
        run = db.get(GeoAgentRun, 1)
        action = db.get(GeoOptimizationAction, 1)
        db.add(
            GeoAgentEvent(
                workspace_id=1,
                agent_run_id=1,
                sequence=1,
                event_type="awaiting_human_review",
                stage="awaiting_review",
                message="上一版已经进入人工审核",
                detail={},
            )
        )
        run.status = "resuming"
        run.stage = "queued"
        action.stage = "generating"
        db.commit()

        result = agent_orchestration.execute_agent_run(db, run, runtime=TimeoutRuntime())
        assert result.status == "failed"
        assert result.stage == "timed_out"
        assert result.error_code == "agent_timeout"
        assert result.codex_thread_id == "thread-review-1"
        assert action.stage == "blocked"
        assert "900 seconds" in action.blocked_reason

    events = review_client.get("/api/v1/workspaces/1/agent-runs/1/events")
    assert events.status_code == 200
    assert events.json()[-1]["event_type"] == "run_timed_out"

    progress = review_client.get("/api/v1/workspaces/1/agent-runs/1/progress")
    assert progress.status_code == 200
    assert progress.json()["progress_percent"] == 10
    assert [stage["state"] for stage in progress.json()["stages"]] == [
        "done",
        "failed",
        "waiting",
        "waiting",
        "waiting",
    ]
