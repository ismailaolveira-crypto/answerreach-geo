from __future__ import annotations

import pytest

from app.services import office_collaboration as office


@pytest.mark.parametrize(
    ("provider", "credentials", "token_key"),
    [
        ("wecom", {"corp_id": "corp", "agent_id": "1", "app_secret": "secret"}, "access_token"),
        ("feishu", {"app_id": "app", "app_secret": "secret"}, "tenant_access_token"),
        ("dingtalk", {"app_key": "key", "agent_id": "2", "app_secret": "secret"}, "accessToken"),
    ],
)
def test_app_connection_accepts_only_real_token_response(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    credentials: dict[str, str],
    token_key: str,
) -> None:
    def fake_request(*args, **kwargs):
        if provider == "wecom":
            return {"errcode": 0, token_key: "token"}
        if provider == "feishu":
            return {"code": 0, token_key: "token"}
        return {token_key: "token", "expireIn": 7200}

    monkeypatch.setattr(office, "_request", fake_request)
    result = office.test_connection(provider, "app", credentials)
    assert result.accepted is True
    assert result.evidence == {"authentication": "accepted", "message_sent": False}


def test_app_connection_rejects_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(office, "_request", lambda *args, **kwargs: {"errcode": 40013})
    with pytest.raises(office.OfficeProviderError, match="authentication_rejected"):
        office.test_connection(
            "wecom",
            "app",
            {"corp_id": "corp", "agent_id": "1", "app_secret": "wrong"},
        )


def test_webhook_requires_official_https_host() -> None:
    with pytest.raises(office.OfficeProviderError, match="invalid_webhook_host"):
        office.validate_configuration(
            "feishu", "webhook", {"webhook_url": "https://example.com/hook"}
        )


@pytest.mark.parametrize("provider", ["wecom", "feishu", "dingtalk"])
def test_webhook_payload_is_provider_specific(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    seen: dict = {}

    def fake_request(method, url, **kwargs):
        seen.update(kwargs["json_body"])
        if provider == "feishu":
            return {"StatusCode": 0, "StatusMessage": "success"}
        return {"errcode": 0, "errmsg": "ok"}

    monkeypatch.setattr(office, "_request", fake_request)
    host = {
        "wecom": "qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x",
        "feishu": "open.feishu.cn/open-apis/bot/v2/hook/x",
        "dingtalk": "oapi.dingtalk.com/robot/send?access_token=x",
    }[provider]
    result = office.send_message(
        provider,
        "webhook",
        {"webhook_url": f"https://{host}"},
        text="GEO 进度",
        external_user_id=None,
        external_id_type="user_id",
    )
    assert result.accepted is True
    assert seen["msg_type" if provider == "feishu" else "msgtype"] in {"text", "markdown"}


@pytest.mark.parametrize("provider", ["wecom", "feishu", "dingtalk"])
def test_direct_send_reports_provider_acceptance_not_delivery(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    calls: list[tuple[str, str, dict]] = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if "gettoken" in url:
            return {"errcode": 0, "access_token": "token"}
        if "tenant_access_token" in url:
            return {"code": 0, "tenant_access_token": "token"}
        if "oauth2/accessToken" in url:
            return {"accessToken": "token"}
        if provider == "feishu":
            return {"code": 0, "data": {"message_id": "om_1"}}
        if provider == "dingtalk":
            return {"errcode": 0, "task_id": 31}
        return {"errcode": 0, "errmsg": "ok", "msgid": "ignored"}

    monkeypatch.setattr(office, "_request", fake_request)
    credentials = {
        "wecom": {"corp_id": "corp", "agent_id": "1", "app_secret": "secret"},
        "feishu": {"app_id": "app", "app_secret": "secret"},
        "dingtalk": {"app_key": "key", "agent_id": "2", "app_secret": "secret"},
    }[provider]
    result = office.send_message(
        provider,
        "app",
        credentials,
        text="请查看 GEO 工作进度",
        external_user_id="user-1",
        external_id_type="open_id" if provider == "feishu" else "user_id",
    )
    assert result.accepted is True
    assert "delivered" not in result.evidence
    assert "read" not in result.evidence
    assert len(calls) == 2
