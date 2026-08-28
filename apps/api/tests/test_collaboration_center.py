from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
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
from app.models.collaboration import (
    GeoCollaborationAttachment,
    GeoCollaborationMessage,
    GeoCollaborationThread,
)
from app.models.company import Company
from app.models.cleanroom_v1 import (
    GeoActionTarget,
    GeoEvidence,
    GeoObservationRun,
    GeoOptimizationAction,
    GeoQuestionPlan,
    GeoWorkspace,
)
from app.models.user import User
from app.services.workspace_access import add_membership


@pytest.fixture
def collaboration_client(tmp_path, monkeypatch) -> Generator[TestClient, None, None]:
    monkeypatch.setattr("app.v1.collaboration_routes.UPLOAD_ROOT", tmp_path / "uploads")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with sessions() as db:
        db.add(Company(id=1, name="测试企业"))
        db.add_all(
            [
                User(id=1, company_id=1, name="王经理", email="owner@collab.test", role="company_admin"),
                User(id=2, company_id=1, name="李同学", email="operator@collab.test", role="content_operator"),
            ]
        )
        db.add(
            GeoWorkspace(
                id=1,
                company_id=1,
                slug="collaboration-center",
                brand_name="春秋元泉",
                brand_aliases=[],
                website_url="https://example.com",
            )
        )
        db.flush()
        add_membership(db, workspace_id=1, user_id=1, role="owner")
        add_membership(db, workspace_id=1, user_id=2, role="operator")
        db.add(
            GeoOptimizationAction(
                id=1,
                workspace_id=1,
                title="发布知乎对比证据文章",
                rationale="重要问题仍缺少可引用的官方证据",
                priority="high",
                status="accepted",
                stage="in_progress",
                baseline_snapshot={},
                selected_scope={},
                measurement_plan={},
                action_type="article",
                deliverable_type="platform_article",
                workflow_version="action-flow.v2",
                assignee_user_id=2,
                affected_question_ids=[7],
                affected_model_keys=["glm", "qianwen"],
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
                delivery_status="awaiting_fact_review",
                ordinal=0,
                metadata_json={},
            )
        )
        db.add(
            GeoQuestionPlan(
                id=7,
                workspace_id=1,
                question_text="企业如何统一管理多模型 API 密钥和成本？",
                topic_tags=["Token 管理"],
                importance=5,
            )
        )
        db.add(
            GeoObservationRun(
                id=9,
                workspace_id=1,
                adapter_key="test-provider",
                status="completed",
                request_context={},
            )
        )
        db.add(
            GeoEvidence(
                id=21,
                workspace_id=1,
                run_id=9,
                question_plan_id=7,
                model_key="glm",
                model_label="智谱 GLM",
                prompt_version="v1",
                sample_mode="official_api",
                evidence_level="provider_response",
                collection_method="official_api",
                evidence_kind="model_answer",
                is_real_provider_evidence=True,
                brand_status="absent",
                competitor_positions=[],
                answer_text="回答提到了成本治理，但尚未出现春秋元泉。",
                answer_hash="collaboration-evidence-21",
                source_items=[{"url": "https://example.com/source"}],
                sampling_environment={},
                captured_at=datetime(2026, 8, 27, 8, 0, tzinfo=UTC),
            )
        )
        db.commit()

    app = create_app()
    current = SimpleNamespace(id=1, company_id=1, role="company_admin")

    def override_db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: current
    client = TestClient(app)
    client.app.state.collaboration_sessions = sessions
    yield client
    app.dependency_overrides.clear()
    engine.dispose()


def test_center_is_derived_from_real_action_and_disconnected_channels(
    collaboration_client: TestClient,
) -> None:
    response = collaboration_client.get("/api/v1/workspaces/1/collaboration")
    assert response.status_code == 200, response.text
    payload = response.json()
    action = next(item for item in payload["items"] if item["context_type"] == "action")
    assert action["title"] == "发布知乎对比证据文章"
    assert action["assignee_name"] == "李同学"
    assert action["progress"] > 0
    assert any(item["context_type"] == "question" for item in payload["items"])
    assert {channel["status"] for channel in payload["channels"]} == {"disconnected"}


def test_message_is_persisted_idempotently_and_read_back(
    collaboration_client: TestClient,
) -> None:
    body = {
        "context_type": "action",
        "context_id": 1,
        "body": "请帮忙审核知乎平台稿。",
        "mention_user_ids": [2],
        "attachment_refs": [
            {"label": "证据页", "url": "https://example.com/evidence", "kind": "evidence"}
        ],
        "idempotency_key": "message-test-0001",
    }
    first = collaboration_client.post(
        "/api/v1/workspaces/1/collaboration/messages", json=body
    )
    second = collaboration_client.post(
        "/api/v1/workspaces/1/collaboration/messages", json=body
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["message"]["body"] == body["body"]
    assert first.json()["message"]["author"]["name"] == "王经理"
    with collaboration_client.app.state.collaboration_sessions() as db:
        assert db.scalar(select(func.count(GeoCollaborationThread.id))) == 1
        assert db.scalar(select(func.count(GeoCollaborationMessage.id))) == 1
    center = collaboration_client.get(
        "/api/v1/workspaces/1/collaboration?context_type=action&context_id=1"
    ).json()
    selected = center["selected"]
    assert selected["has_conversation"] is True
    assert selected["message_count"] == 1
    assert selected["last_message_preview"] == body["body"]
    assert selected["last_message_author_name"] == "王经理"
    assert center["selected_detail"]["messages"][0]["body"] == body["body"]
    assert center["selected_detail"]["messages"][0]["mention_user_ids"] == [2]


def test_message_rejects_member_outside_workspace(collaboration_client: TestClient) -> None:
    response = collaboration_client.post(
        "/api/v1/workspaces/1/collaboration/messages",
        json={
            "context_type": "action",
            "context_id": 1,
            "body": "请外部人员查看",
            "mention_user_ids": [999],
            "attachment_refs": [],
            "idempotency_key": "message-test-0002",
        },
    )
    assert response.status_code == 422


def test_question_discussion_is_persisted_and_read_back(
    collaboration_client: TestClient,
) -> None:
    created = collaboration_client.post(
        "/api/v1/workspaces/1/collaboration/messages",
        json={
            "context_type": "question",
            "context_id": 7,
            "body": "这个问题先确认采购角色和评估口径。",
            "mention_user_ids": [2],
            "attachment_refs": [],
            "idempotency_key": "question-message-0001",
        },
    )
    assert created.status_code == 201, created.text
    center = collaboration_client.get(
        "/api/v1/workspaces/1/collaboration?context_type=question&context_id=7"
    )
    assert center.status_code == 200, center.text
    payload = center.json()
    assert payload["selected"]["context_type"] == "question"
    assert payload["selected"]["title"] == "企业如何统一管理多模型 API 密钥和成本？"
    assert payload["selected"]["has_conversation"] is True
    assert payload["selected_detail"]["questions"] == [
        {"id": 7, "text": "企业如何统一管理多模型 API 密钥和成本？"}
    ]
    assert payload["selected_detail"]["messages"][0]["mention_user_ids"] == [2]


def test_evidence_result_can_start_a_real_discussion(
    collaboration_client: TestClient,
) -> None:
    center = collaboration_client.get("/api/v1/workspaces/1/collaboration").json()
    evidence = next(item for item in center["items"] if item["context_type"] == "evidence")
    assert evidence["context_id"] == 21
    assert evidence["title"] == "企业如何统一管理多模型 API 密钥和成本？"
    assert evidence["model_keys"] == ["glm"]
    created = collaboration_client.post(
        "/api/v1/workspaces/1/collaboration/messages",
        json={
            "context_type": "evidence",
            "context_id": 21,
            "body": "请核对这次模型回答中的证据缺口。",
            "mention_user_ids": [2],
            "idempotency_key": "evidence-message-0001",
        },
    )
    assert created.status_code == 201, created.text
    selected = collaboration_client.get(
        "/api/v1/workspaces/1/collaboration?context_type=evidence&context_id=21"
    ).json()
    assert selected["selected"]["has_conversation"] is True
    assert selected["selected_detail"]["summary"].startswith("回答提到了")


def test_work_info_updates_action_and_reads_back_for_any_context(
    collaboration_client: TestClient,
) -> None:
    payload = {
        "assignee_user_id": 2,
        "start_at": "2026-08-27T00:00:00Z",
        "due_at": "2026-09-05T00:00:00Z",
        "participant_user_ids": [1, 2],
    }
    action = collaboration_client.patch(
        "/api/v1/workspaces/1/collaboration/contexts/action/1/work-info",
        json=payload,
    )
    assert action.status_code == 200, action.text
    selected = action.json()["selected"]
    assert selected["assignee_name"] == "李同学"
    assert selected["start_at"].startswith("2026-08-27")
    assert selected["due_at"].startswith("2026-09-05")
    assert selected["participant_user_ids"] == [1, 2]

    evidence = collaboration_client.patch(
        "/api/v1/workspaces/1/collaboration/contexts/evidence/21/work-info",
        json=payload,
    )
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["selected"]["context_type"] == "evidence"
    assert evidence.json()["selected"]["assignee_user_id"] == 2


def test_private_image_upload_is_attached_and_read_back(
    collaboration_client: TestClient,
) -> None:
    raw = b"\x89PNG\r\n\x1a\n" + b"collaboration-image"
    uploaded = collaboration_client.post(
        "/api/v1/workspaces/1/collaboration/attachments",
        content=raw,
        headers={
            "content-type": "image/png",
            "x-file-name": "review-shot.png",
            "x-file-size": str(len(raw)),
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    attachment = uploaded.json()
    assert attachment["kind"] == "image"
    created = collaboration_client.post(
        "/api/v1/workspaces/1/collaboration/messages",
        json={
            "context_type": "action",
            "context_id": 1,
            "body": "",
            "mention_user_ids": [],
            "attachment_ids": [attachment["attachment_id"]],
            "shared_objects": [{"kind": "action", "object_id": 1}],
            "idempotency_key": "message-media-0001",
        },
    )
    assert created.status_code == 201, created.text
    file_response = collaboration_client.get(
        f"/api/v1/workspaces/1/collaboration/attachments/{attachment['attachment_id']}"
    )
    assert file_response.status_code == 200
    assert file_response.content == raw
    center = collaboration_client.get(
        "/api/v1/workspaces/1/collaboration?context_type=action&context_id=1"
    ).json()
    refs = center["selected_detail"]["messages"][0]["attachment_refs"]
    assert [item["kind"] for item in refs] == ["image", "geo_object"]
    assert refs[1]["title"] == "发布知乎对比证据文章"
    with collaboration_client.app.state.collaboration_sessions() as db:
        row = db.get(GeoCollaborationAttachment, attachment["attachment_id"])
        assert row.status == "attached"
        assert row.message_id == created.json()["id"]


def test_upload_rejects_unknown_type(collaboration_client: TestClient) -> None:
    response = collaboration_client.post(
        "/api/v1/workspaces/1/collaboration/attachments",
        content=b"binary",
        headers={"content-type": "application/x-executable", "x-file-name": "run.bin"},
    )
    assert response.status_code == 415


def test_channel_only_accepts_official_webhook_host(collaboration_client: TestClient) -> None:
    rejected = collaboration_client.put(
        "/api/v1/workspaces/1/collaboration/channels/wecom",
        json={
            "provider": "wecom",
            "webhook_url": "https://example.com/not-official",
            "display_name": "GEO 通知",
        },
    )
    assert rejected.status_code == 422
    accepted = collaboration_client.put(
        "/api/v1/workspaces/1/collaboration/channels/wecom",
        json={
            "provider": "wecom",
            "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
            "display_name": "GEO 通知",
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "configured"
