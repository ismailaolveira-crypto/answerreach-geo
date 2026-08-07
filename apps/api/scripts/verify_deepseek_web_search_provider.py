"""Contract test for DeepSeek official API plus Web Search."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.llm_provider import DeepSeekWebSearchProvider  # noqa: E402


def main() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "server_tool_use", "id": "srv_1", "name": "web_search", "input": {"query": "企业大模型治理平台"}},
                    {
                        "type": "web_search_tool_result",
                        "tool_use_id": "srv_1",
                        "content": [
                            {"type": "web_search_result", "title": "企业治理白皮书", "url": "https://example.com/report", "page_age": "2 days ago"},
                            {"type": "web_search_result", "title": "重复来源", "url": "https://example.com/report"},
                        ],
                    },
                    {"type": "text", "text": "选型时应重点核验私有化部署、审计和模型兼容性。"},
                ],
                "stop_reason": "end_turn",
            },
        )

    provider = SimpleNamespace(
        name="DeepSeek 官方联网 GEO 采集",
        model_name="deepseek-v4-pro",
        api_base_url="https://api.deepseek.com/anthropic",
        auth_config={},
        cost_rule={},
    )
    adapter = DeepSeekWebSearchProvider(provider, api_key="test-key", transport=httpx.MockTransport(handler))
    answer = adapter.answer(
        "企业级大模型治理平台怎么选？",
        SimpleNamespace(name="春秋元泉"),
        SimpleNamespace(name="GEO"),
        [],
    )
    assert captured["url"] == "https://api.deepseek.com/anthropic/v1/messages"
    assert captured["payload"]["tools"][0]["type"] == "web_search_20250305"
    assert captured["payload"]["thinking"] == {"type": "disabled"}
    assert captured["payload"]["output_config"] == {"effort": "low"}
    assert captured["payload"]["messages"][0]["content"][0]["text"] == "企业级大模型治理平台怎么选？"
    assert answer.collection_method == "official_api_web_search"
    assert answer.search_verified is True
    assert answer.search_event_count == 2
    assert answer.search_verification["source_count"] == 1
    assert answer.raw_answer.startswith("选型时应重点核验")
    assert answer.source_items == [
        {
            "number": 1,
            "title": "企业治理白皮书",
            "url": "https://example.com/report",
            "domain": "example.com",
            "page_age": "2 days ago",
        }
    ]
    assert answer.raw_provider_payload["id"] == "msg_test"

    def incomplete_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "content": [
                {"type": "web_search_tool_result", "tool_use_id": "missing_call", "content": [
                    {"type": "web_search_result", "title": "来源", "url": "https://example.com/source"}
                ]},
                {"type": "text", "text": "这段回答有来源，但没有实际搜索调用证据。"},
            ]
        })

    incomplete = DeepSeekWebSearchProvider(provider, api_key="test-key", transport=httpx.MockTransport(incomplete_handler))
    try:
        incomplete.answer("必须联网吗？", SimpleNamespace(name="春秋元泉"), SimpleNamespace(name="GEO"), [])
    except ValueError as exc:
        assert "completed Web Search tool call" in str(exc)
    else:
        raise AssertionError("Unverified search response must be rejected")
    print(json.dumps({"ok": True, "endpoint": captured["url"], "sources": 1}, ensure_ascii=False))


if __name__ == "__main__":
    main()
