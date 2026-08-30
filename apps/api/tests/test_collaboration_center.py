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
from app.core.config import Settings
from app.db.session import Base, get_db
from app.main import create_app
from app.models.collaboration import (
    GeoCollaborationAttachment,
    GeoCollaborationDelivery,
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
from app.services.office_collaboration import ProviderResult
from app.v1 import collaboration_routes


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


def test_attachment_workspace_quota_blocks_before_second_file_is_written(
    collaboration_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        collaboration_workspace_storage_quota_bytes=20,
        collaboration_user_storage_quota_bytes=20,
        collaboration_attachment_count_quota=10,
        collaboration_upload_rate_limit_per_10_minutes=10,
    )
    monkeypatch.setattr(collaboration_routes, "get_settings", lambda: settings)
    first = b"first-file-1"
    created = collaboration_client.post(
        "/api/v1/workspaces/1/collaboration/attachments",
        content=first,
        headers={
            "content-type": "text/plain",
            "x-file-name": "first.txt",
            "x-file-size": str(len(first)),
        },
    )
    assert created.status_code == 201, created.text
    second = b"second-file"
    blocked = collaboration_client.post(
        "/api/v1/workspaces/1/collaboration/attachments",
        content=second,
        headers={
            "content-type": "text/plain",
            "x-file-name": "second.txt",
            "x-file-size": str(len(second)),
        },
    )
    assert blocked.status_code == 413
    assert blocked.json()["detail"] == "工作区附件存储空间不足"
    assert len(list(collaboration_routes.UPLOAD_ROOT.rglob("*.*"))) == 1


def test_attachment_upload_rate_limit_is_persistent(
    collaboration_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        collaboration_upload_rate_limit_per_10_minutes=1,
    )
    monkeypatch.setattr(collaboration_routes, "get_settings", lambda: settings)
    first = collaboration_client.post(
        "/api/v1/workspaces/1/collaboration/attachments",
        content=b"first",
        headers={
            "content-type": "text/plain",
            "x-file-name": "first.txt",
            "x-file-size": "5",
        },
    )
    assert first.status_code == 201, first.text
    blocked = collaboration_client.post(
        "/api/v1/workspaces/1/collaboration/attachments",
        content=b"second",
        headers={
            "content-type": "text/plain",
            "x-file-name": "second.txt",
            "x-file-size": "6",
        },
    )
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


def test_attachment_rejects_underdeclared_size_without_persisting_file(
    collaboration_client: TestClient,
) -> None:
    before = set(collaboration_routes.UPLOAD_ROOT.rglob("*.*"))
    rejected = collaboration_client.post(
        "/api/v1/workspaces/1/collaboration/attachments",
        content=b"actual-file-content",
        headers={
            "content-type": "text/plain",
            "x-file-name": "underdeclared.txt",
            "x-file-size": "1",
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "文件大小与声明不一致"
    assert set(collaboration_routes.UPLOAD_ROOT.rglob("*.*")) == before


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

    edited = collaboration_client.put(
        "/api/v1/workspaces/1/collaboration/channels/wecom",
        json={
            "provider": "wecom",
            "connection_mode": "webhook",
            "display_name": "品牌增长组",
            "deep_link_base_url": "https://geo.example.com",
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["display_name"] == "品牌增长组"
    assert edited.json()["configured_fields"] == ["webhook_url"]


def test_app_channel_binding_preferences_preview_and_send_are_persisted(
    collaboration_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = collaboration_client.put(
        "/api/v1/workspaces/1/collaboration/channels/feishu",
        json={
            "provider": "feishu",
            "connection_mode": "app",
            "app_id": "cli_test",
            "app_secret": "private-value",
            "display_name": "春秋元泉 GEO",
            "deep_link_base_url": "https://geo.example.com",
        },
    )
    assert configured.status_code == 200, configured.text
    assert configured.json()["configured_fields"] == ["app_id", "app_secret"]
    assert "private-value" not in configured.text

    monkeypatch.setattr(
        "app.v1.collaboration_routes.test_office_connection",
        lambda *args, **kwargs: ProviderResult(True, None, {"authentication": "accepted"}),
    )
    tested = collaboration_client.post(
        "/api/v1/workspaces/1/collaboration/channels/feishu/test"
    )
    assert tested.status_code == 200, tested.text
    assert tested.json()["status"] == "connected"
    assert tested.json()["connection_mode"] == "app"

    monkeypatch.setattr(
        "app.v1.collaboration_routes.verify_office_member",
        lambda *args, **kwargs: {
            "external_user_id": "ou_verified",
            "external_display_name": "李同学",
        },
    )
    bound = collaboration_client.put(
        "/api/v1/workspaces/1/collaboration/members/2/bindings/feishu",
        json={"external_user_id": "ou_candidate", "external_id_type": "open_id"},
    )
    assert bound.status_code == 200, bound.text
    assert bound.json()["bindings"][0]["status"] == "verified"
    assert "ou_verified" not in bound.text

    preference = collaboration_client.put(
        "/api/v1/workspaces/1/collaboration/members/2/notification-preferences",
        json={
            "provider_settings": {"wecom": False, "feishu": True, "dingtalk": False},
            "event_types": ["manual_summary", "assigned"],
        },
    )
    assert preference.status_code == 200, preference.text
    assert preference.json()["notification_preferences"]["provider_settings"]["feishu"] is True

    preview_payload = {
        "recipient_user_id": 2,
        "context_type": "action",
        "context_id": 1,
        "event_type": "manual_summary",
        "providers": ["feishu"],
        "note": "请今天确认审核意见",
    }
    preview = collaboration_client.post(
        "/api/v1/workspaces/1/collaboration/notifications/preview",
        json=preview_payload,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["external_write_performed"] is False
    assert preview.json()["providers"][0]["ready"] is True
    assert "发布知乎对比证据文章" in preview.json()["message_preview"]

    monkeypatch.setattr(
        "app.v1.collaboration_routes.send_office_message",
        lambda *args, **kwargs: ProviderResult(True, "om_test", {"message_id": "om_test"}),
    )
    sent = collaboration_client.post(
        "/api/v1/workspaces/1/collaboration/notifications/send",
        json={**preview_payload, "idempotency_key": "office-send-0001"},
    )
    repeated = collaboration_client.post(
        "/api/v1/workspaces/1/collaboration/notifications/send",
        json={**preview_payload, "idempotency_key": "office-send-0001"},
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["results"][0]["status"] == "provider_accepted"
    assert repeated.json()["results"][0]["id"] == sent.json()["results"][0]["id"]
    assert "已读" in sent.json()["truth_note"]
    with collaboration_client.app.state.collaboration_sessions() as db:
        assert db.scalar(select(func.count(GeoCollaborationDelivery.id))) == 1


def test_notification_is_blocked_when_member_preference_is_off(
    collaboration_client: TestClient,
) -> None:
    response = collaboration_client.post(
        "/api/v1/workspaces/1/collaboration/notifications/preview",
        json={
            "recipient_user_id": 2,
            "context_type": "action",
            "context_id": 1,
            "event_type": "manual_summary",
            "providers": ["wecom"],
        },
    )
    assert response.status_code == 200
    assert response.json()["providers"][0]["ready"] is False
    assert response.json()["external_write_performed"] is False
