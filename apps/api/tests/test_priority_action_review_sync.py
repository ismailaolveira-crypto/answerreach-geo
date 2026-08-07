from collections.abc import Generator
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
    GeoContentAsset,
    GeoContentBrief,
    GeoContentClaim,
    GeoOptimizationAction,
    GeoPlatformVariant,
    GeoWorkspace,
)
from app.models.user import User


@pytest.fixture
def review_client() -> Generator[TestClient, None, None]:
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
            ]
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
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_review_gate_and_browser_client_draft_readback(review_client: TestClient) -> None:
    package = review_client.get("/api/v1/workspaces/1/content-assets/1/review-package")
    assert package.status_code == 200
    assert package.json()["pending_claim_count"] == 1

    blocked_review = review_client.post(
        "/api/v1/workspaces/1/content-assets/1/reviews",
        json={"verdict": "approved", "confirmed_claim_ids": [], "platform_keys": ["zhihu"]},
    )
    assert blocked_review.status_code == 422

    approved = review_client.post(
        "/api/v1/workspaces/1/content-assets/1/reviews",
        json={
            "verdict": "approved",
            "confirmed_claim_ids": [2],
            "platform_keys": ["zhihu"],
            "note": "已与品牌负责人核对",
        },
    )
    assert approved.status_code == 201
    assert approved.json()["approved_platform_keys"] == ["zhihu"]
    assert approved.json()["pending_claim_count"] == 0

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

