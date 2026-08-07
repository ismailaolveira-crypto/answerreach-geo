from collections.abc import Generator
import json
from pathlib import Path
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
    GeoAgentRun,
    GeoContentBrief,
    GeoContentClaim,
    GeoOptimizationAction,
    GeoPlatformVariant,
    GeoWorkspace,
)
from app.models.user import User
from app.v1 import agent_orchestration


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
    assert persisted.json()["targets"][0]["human_publish_status"] == "awaiting_publish"

    target_id = persisted.json()["targets"][0]["id"]
    wrong_platform = review_client.post(
        f"/api/v1/workspaces/1/distribution-runs/{run_id}/targets/{target_id}/human-publication",
        json={"public_url": "https://example.com/articles/not-zhihu"},
    )
    assert wrong_platform.status_code == 422

    published = review_client.post(
        f"/api/v1/workspaces/1/distribution-runs/{run_id}/targets/{target_id}/human-publication",
        json={"public_url": "https://zhuanlan.zhihu.com/p/123456789"},
    )
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    assert published.json()["targets"][0]["human_publish_status"] == "published"
    assert published.json()["targets"][0]["publication_verification_status"] == "human_confirmed"
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
