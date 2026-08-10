import json
from datetime import datetime, timezone

import httpx
import pytest
from pydantic import ValidationError

from app.models import Company, LLMProvider, Project
from app.services.llm_provider import (
    DeepSeekWebSearchProvider,
    HunyuanWebSearchProvider,
    KimiWebSearchProvider,
    diagnose_provider,
)
from app.v1.schemas import YaoDatasetImport


def _provider(provider_type: str, model: str, base_url: str) -> LLMProvider:
    return LLMProvider(
        name=provider_type,
        provider_type=provider_type,
        api_base_url=base_url,
        model_name=model,
        auth_config={},
        cost_rule={},
        status="active",
    )


COMPANY = Company(name="春秋元泉", industry="software", website_url=None, brand_aliases=[])
PROJECT = Project(company_id=1, name="test", target_industry="software", target_audience="buyer")


def test_deepseek_uses_official_anthropic_server_search_protocol() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "server_tool_use", "id": "srv_1", "name": "web_search"},
                    {
                        "type": "web_search_tool_result",
                        "tool_use_id": "srv_1",
                        "content": [
                            {
                                "type": "web_search_result",
                                "title": "Official result",
                                "url": "https://example.com/deepseek-source",
                            }
                        ],
                    },
                    {"type": "text", "text": "DeepSeek answer"},
                ]
            },
        )

    adapter = DeepSeekWebSearchProvider(
        _provider("deepseek_web_search", "deepseek-v4-flash", "https://api.deepseek.com/anthropic"),
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )
    answer = adapter.answer("今天有什么新消息？", COMPANY, PROJECT, [])

    assert captured["path"] == "/anthropic/v1/messages"
    assert captured["payload"]["tools"] == [
        {"type": "web_search_20250305", "name": "web_search", "max_uses": 4}
    ]
    assert captured["payload"]["tool_choice"] == {"type": "any"}
    assert answer.search_verified is True
    assert answer.source_items[0]["url"] == "https://example.com/deepseek-source"
    assert answer.search_verification["observation_surface"] == "official_api"
    assert answer.search_verification["web_ui_equivalence"] == "not_claimed"


def test_kimi_k3_executes_official_formula_and_requires_structured_sources() -> None:
    chat_round = 0
    captured_fiber: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal chat_round
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "tools": [
                        {
                            "type": "function",
                            "function": {
                                "name": "web_search",
                                "description": "Search the web",
                                "parameters": {"type": "object"},
                            },
                        }
                    ]
                },
            )
        if request.url.path.endswith("/fibers"):
            captured_fiber.update(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "id": "fiber_1",
                    "status": "succeeded",
                    "context": {"encrypted_output": "----MOONSHOT ENCRYPTED----"},
                },
            )
        chat_round += 1
        payload = json.loads(request.content)
        assert payload["model"] == "kimi-k3"
        if chat_round == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "web_search:0",
                                        "type": "function",
                                        "function": {
                                            "name": "web_search",
                                            "arguments": '{"query":"latest"}',
                                        },
                                    }
                                ],
                            },
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "Kimi answer",
                            "annotations": [
                                {
                                    "title": "Kimi source",
                                    "url": "https://example.com/kimi-source",
                                }
                            ],
                        },
                    }
                ]
            },
        )

    adapter = KimiWebSearchProvider(
        _provider("kimi_web_search", "kimi-k3", "https://api.moonshot.cn/v1"),
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )
    answer = adapter.answer("请联网搜索", COMPANY, PROJECT, [])

    assert captured_fiber == {"name": "web_search", "arguments": '{"query":"latest"}'}
    assert answer.source_items[0]["url"] == "https://example.com/kimi-source"
    assert answer.search_verification["formula_uri"] == "moonshot/web-search:latest"
    assert answer.search_verification["web_ui_equivalence"] == "not_claimed"


def test_hunyuan_uses_tokenhub_responses_web_search() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "output": [
                    {"type": "web_search_call", "id": "ws_1", "status": "completed"},
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Hunyuan answer",
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "title": "Tencent source",
                                        "url": "https://example.com/hunyuan-source",
                                    }
                                ],
                            }
                        ],
                    },
                ]
            },
        )

    adapter = HunyuanWebSearchProvider(
        _provider("hunyuan_web_search", "hy3-preview", "https://tokenhub.tencentmaas.com/v1"),
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )
    answer = adapter.answer("请联网搜索", COMPANY, PROJECT, [])

    assert captured["url"] == "https://tokenhub.tencentmaas.com/v1/responses"
    assert captured["payload"]["model"] == "hy3-preview"
    assert captured["payload"]["tools"] == [
        {"type": "web_search", "search_source": "lite", "search_context_size": "medium"}
    ]
    assert answer.source_items[0]["url"] == "https://example.com/hunyuan-source"
    assert answer.search_verification["protocol"] == "tokenhub_responses"
    assert answer.search_verification["web_ui_equivalence"] == "not_claimed"


def test_legacy_hunyuan_configuration_is_not_reported_ready() -> None:
    provider = _provider(
        "hunyuan_web_search",
        "hunyuan-turbos-latest",
        "https://api.hunyuan.cloud.tencent.com/v1",
    )
    provider.auth_config = {"api_key": "test-key"}

    diagnostic = diagnose_provider(provider)

    assert diagnostic["ready"] is False
    assert "tokenhub_base_url" in diagnostic["missing"]
    assert "model_name=hy3-preview" in diagnostic["missing"]


def _auditable_web_payload(platform: str, conversation_url: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "platform": platform,
        "sample_mode": "browser_assisted",
        "evidence_level": "auditable",
        "observation_group_id": "group_20260810",
        "samples": [
            {
                "sample_id": "sample-1",
                "question": "same exact question",
                "repeat_index": 1,
                "ok": True,
                "started_at": now,
                "finished_at": now,
                "raw_artifact_uri": "file:///private/answer.json",
                "screenshot_uri": "file:///private/page.png",
                "conversation_url": conversation_url,
                "answer_text": "answer",
                "references": [{"title": "source", "url": "https://example.com/source"}],
                "web_ui_context": {
                    "account_alias": "audit-a",
                    "account_fingerprint": "a" * 64,
                    "model_display_name": "displayed model",
                    "search_setting": "explicit_on",
                    "new_conversation": True,
                    "locale": "zh-CN",
                    "timezone": "Asia/Shanghai",
                    "settings_snapshot_sha256": "b" * 64,
                },
            }
        ],
    }


@pytest.mark.parametrize(
    ("platform", "url"),
    [
        ("deepseek", "https://chat.deepseek.com/a/chat/s/1"),
        ("kimi", "https://www.kimi.com/chat/1"),
        ("yuanbao", "https://yuanbao.tencent.com/chat/1"),
    ],
)
def test_auditable_web_ui_contract_accepts_only_official_surfaces(
    platform: str, url: str
) -> None:
    dataset = YaoDatasetImport.model_validate(_auditable_web_payload(platform, url))
    assert dataset.observation_group_id == "group_20260810"
    assert dataset.samples[0].web_ui_context is not None


def test_auditable_web_ui_contract_rejects_api_or_unofficial_url() -> None:
    payload = _auditable_web_payload("kimi", "https://api.moonshot.cn/v1/chat/completions")
    with pytest.raises(ValidationError, match="conversation URL must use www.kimi.com"):
        YaoDatasetImport.model_validate(payload)
