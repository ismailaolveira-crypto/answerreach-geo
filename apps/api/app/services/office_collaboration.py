"""Official office-platform adapters for collaboration notifications.

The service deliberately exposes the strongest fact shared by all three providers:
the provider accepted or rejected a request.  It never upgrades that fact to
"delivered" or "read" without a provider callback proving it.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx


Provider = Literal["wecom", "feishu", "dingtalk"]
ConnectionMode = Literal["webhook", "app"]

PROVIDER_LABELS: dict[str, str] = {
    "wecom": "企业微信",
    "feishu": "飞书",
    "dingtalk": "钉钉",
}
WEBHOOK_HOSTS: dict[str, set[str]] = {
    "wecom": {"qyapi.weixin.qq.com"},
    "feishu": {"open.feishu.cn"},
    "dingtalk": {"oapi.dingtalk.com"},
}
APP_FIELDS: dict[str, tuple[str, ...]] = {
    "wecom": ("corp_id", "agent_id", "app_secret"),
    "feishu": ("app_id", "app_secret"),
    "dingtalk": ("app_key", "agent_id", "app_secret"),
}
WEBHOOK_FIELDS = ("webhook_url",)
CAPABILITIES: dict[str, dict[str, dict[str, bool]]] = {
    provider: {
        "webhook": {
            "group_broadcast": True,
            "member_binding": False,
            "direct_message": False,
            "provider_acceptance": True,
            "read_receipt": False,
        },
        "app": {
            "group_broadcast": False,
            "member_binding": True,
            "direct_message": True,
            "provider_acceptance": True,
            "read_receipt": False,
        },
    }
    for provider in PROVIDER_LABELS
}


@dataclass(frozen=True)
class ProviderResult:
    accepted: bool
    provider_message_ref: str | None
    evidence: dict[str, Any]


class OfficeProviderError(RuntimeError):
    def __init__(self, code: str, user_message: str, *, status_code: int = 502):
        super().__init__(code)
        self.code = code
        self.user_message = user_message
        self.status_code = status_code


def required_fields(provider: str, mode: str) -> tuple[str, ...]:
    if provider not in PROVIDER_LABELS:
        raise OfficeProviderError("unsupported_provider", "不支持这个办公平台", status_code=422)
    if mode == "webhook":
        return WEBHOOK_FIELDS
    if mode == "app":
        return APP_FIELDS[provider]
    raise OfficeProviderError("unsupported_mode", "连接方式不正确", status_code=422)


def validate_configuration(provider: str, mode: str, credentials: dict[str, str]) -> list[str]:
    fields = required_fields(provider, mode)
    missing = [field for field in fields if not credentials.get(field, "").strip()]
    if missing:
        raise OfficeProviderError(
            "missing_credentials",
            f"请补全必填项：{', '.join(missing)}",
            status_code=422,
        )
    if mode == "webhook":
        validate_webhook_url(provider, credentials["webhook_url"])
    if provider in {"wecom", "dingtalk"} and mode == "app":
        try:
            int(credentials["agent_id"])
        except (TypeError, ValueError) as exc:
            raise OfficeProviderError(
                "invalid_agent_id", "Agent ID 必须是数字", status_code=422
            ) from exc
    return list(fields)


def validate_webhook_url(provider: str, value: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").lower() not in WEBHOOK_HOSTS.get(provider, set())
        or parsed.username
        or parsed.password
    ):
        raise OfficeProviderError(
            "invalid_webhook_host", "请使用该平台官方 HTTPS 机器人地址", status_code=422
        )


def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        response = httpx.request(
            method,
            url,
            headers=headers,
            params=params,
            json=json_body,
            timeout=8.0,
            follow_redirects=False,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.TimeoutException as exc:
        raise OfficeProviderError("provider_timeout", "官方平台响应超时，请稍后重试") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise OfficeProviderError("provider_http_error", "官方平台未确认请求") from exc
    if not isinstance(payload, dict):
        raise OfficeProviderError("invalid_provider_response", "官方平台返回了无法识别的结果")
    return payload


def _safe_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "code",
        "msg",
        "errcode",
        "errmsg",
        "StatusCode",
        "StatusMessage",
        "request_id",
        "message_id",
        "task_id",
        "processQueryKey",
    )
    result = {key: payload[key] for key in allowed if key in payload}
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("message_id", "task_id", "processQueryKey"):
            if key in data:
                result[key] = data[key]
    return result


def _provider_ok(provider: str, payload: dict[str, Any]) -> bool:
    if provider == "feishu":
        return payload.get("code", payload.get("StatusCode")) == 0
    return payload.get("errcode", payload.get("code")) == 0


def _token(provider: str, credentials: dict[str, str]) -> str:
    if provider == "wecom":
        payload = _request(
            "GET",
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
            params={"corpid": credentials["corp_id"], "corpsecret": credentials["app_secret"]},
        )
        token = payload.get("access_token") if payload.get("errcode") == 0 else None
    elif provider == "feishu":
        payload = _request(
            "POST",
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json_body={"app_id": credentials["app_id"], "app_secret": credentials["app_secret"]},
        )
        token = payload.get("tenant_access_token") if payload.get("code") == 0 else None
    elif provider == "dingtalk":
        payload = _request(
            "POST",
            "https://api.dingtalk.com/v1.0/oauth2/accessToken",
            json_body={"appKey": credentials["app_key"], "appSecret": credentials["app_secret"]},
        )
        token = payload.get("accessToken")
    else:
        raise OfficeProviderError("unsupported_provider", "不支持这个办公平台", status_code=422)
    if not token:
        raise OfficeProviderError("authentication_rejected", "官方平台未通过应用凭证")
    return str(token)


def test_connection(provider: str, mode: str, credentials: dict[str, str]) -> ProviderResult:
    validate_configuration(provider, mode, credentials)
    if mode == "webhook":
        return send_message(
            provider,
            mode,
            credentials,
            text="AnswerReach GEO 协作渠道连接测试。",
            external_user_id=None,
            external_id_type="user_id",
        )
    _token(provider, credentials)
    return ProviderResult(
        accepted=True,
        provider_message_ref=None,
        evidence={"authentication": "accepted", "message_sent": False},
    )


def verify_member(
    provider: str,
    credentials: dict[str, str],
    external_user_id: str,
    external_id_type: str,
) -> dict[str, str | None]:
    token = _token(provider, credentials)
    if provider == "wecom":
        payload = _request(
            "GET",
            "https://qyapi.weixin.qq.com/cgi-bin/user/get",
            params={"access_token": token, "userid": external_user_id},
        )
        ok = payload.get("errcode") == 0 and payload.get("userid")
        name = payload.get("name")
        verified_id = payload.get("userid")
    elif provider == "feishu":
        if external_id_type not in {"open_id", "user_id", "union_id"}:
            raise OfficeProviderError("invalid_external_id_type", "飞书身份类型不正确", status_code=422)
        payload = _request(
            "GET",
            f"https://open.feishu.cn/open-apis/contact/v3/users/{external_user_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"user_id_type": external_id_type},
        )
        user = (payload.get("data") or {}).get("user") or {}
        ok = payload.get("code") == 0 and isinstance(user, dict) and user
        name = user.get("name")
        verified_id = user.get(external_id_type) or external_user_id
    elif provider == "dingtalk":
        payload = _request(
            "GET",
            f"https://api.dingtalk.com/v1.0/contact/users/{external_user_id}",
            headers={"x-acs-dingtalk-access-token": token},
        )
        ok = bool(payload.get("name") or payload.get("unionId") or payload.get("userid"))
        name = payload.get("name")
        verified_id = payload.get("userid") or payload.get("userId") or external_user_id
    else:
        raise OfficeProviderError("unsupported_provider", "不支持这个办公平台", status_code=422)
    if not ok:
        raise OfficeProviderError("member_not_confirmed", "官方通讯录未确认该成员")
    return {
        "external_user_id": str(verified_id),
        "external_display_name": str(name) if name else None,
    }


def send_message(
    provider: str,
    mode: str,
    credentials: dict[str, str],
    *,
    text: str,
    external_user_id: str | None,
    external_id_type: str,
) -> ProviderResult:
    validate_configuration(provider, mode, credentials)
    if mode == "webhook":
        if provider == "feishu":
            body = {"msg_type": "text", "content": {"text": text}}
        elif provider == "dingtalk":
            body = {"msgtype": "markdown", "markdown": {"title": "GEO 工作进度", "text": text}}
        else:
            body = {"msgtype": "markdown", "markdown": {"content": text}}
        payload = _request("POST", credentials["webhook_url"], json_body=body)
    else:
        if not external_user_id:
            raise OfficeProviderError("member_binding_required", "该成员尚未绑定平台账号", status_code=409)
        token = _token(provider, credentials)
        if provider == "wecom":
            payload = _request(
                "POST",
                "https://qyapi.weixin.qq.com/cgi-bin/message/send",
                params={"access_token": token},
                json_body={
                    "touser": external_user_id,
                    "msgtype": "markdown",
                    "agentid": int(credentials["agent_id"]),
                    "markdown": {"content": text},
                    "enable_duplicate_check": 1,
                    "duplicate_check_interval": 1800,
                },
            )
        elif provider == "feishu":
            payload = _request(
                "POST",
                "https://open.feishu.cn/open-apis/im/v1/messages",
                headers={"Authorization": f"Bearer {token}"},
                params={"receive_id_type": external_id_type},
                json_body={
                    "receive_id": external_user_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": text}, ensure_ascii=False),
                },
            )
        else:
            payload = _request(
                "POST",
                "https://oapi.dingtalk.com/topapi/message/corpconversation/asyncsend_v2",
                params={"access_token": token},
                json_body={
                    "agent_id": int(credentials["agent_id"]),
                    "userid_list": external_user_id,
                    "msg": {"msgtype": "text", "text": {"content": text}},
                },
            )
    if not _provider_ok(provider, payload):
        evidence = _safe_evidence(payload)
        code = evidence.get("errcode", evidence.get("code", evidence.get("StatusCode", "rejected")))
        raise OfficeProviderError(f"provider_rejected:{code}", "官方平台拒绝了这次发送")
    evidence = _safe_evidence(payload)
    reference = next(
        (str(evidence[key]) for key in ("message_id", "task_id", "processQueryKey") if evidence.get(key)),
        None,
    )
    return ProviderResult(accepted=True, provider_message_ref=reference, evidence=evidence)
