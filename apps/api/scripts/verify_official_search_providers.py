"""Contract checks for official web-search provider evidence gates."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.llm_provider import (  # noqa: E402
    BailianQwenResponsesProvider,
    DeepSeekWebSearchProvider,
    HunyuanWebSearchProvider,
    KimiWebSearchProvider,
    QwenWebSearchProvider,
    VolcengineWebSearchProvider,
)


def provider(provider_type: str, model_name: str, base_url: str) -> SimpleNamespace:
    return SimpleNamespace(
        name=provider_type,
        provider_type=provider_type,
        model_name=model_name,
        api_base_url=base_url,
        auth_config={},
        cost_rule={"timeout_seconds": 30},
    )


def verify_qwen() -> dict:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={
            "output": {
                "choices": [{"message": {"role": "assistant", "content": "应比较审计、权限和私有化能力。[1]"}}],
                "search_info": {"search_results": [{
                    "index": 1,
                    "title": "企业大模型治理白皮书",
                    "url": "https://example.com/qwen-report",
                    "site_name": "示例研究院",
                }]},
            },
            "usage": {"plugins": {"search": {"count": 1}}},
            "request_id": "qwen-contract",
        })

    adapter = QwenWebSearchProvider(
        provider("qwen_compatible", "qwen-plus", "https://dashscope.aliyuncs.com/api/v1"),
        api_key="test-only",
        transport=httpx.MockTransport(handler),
    )
    prompt = "企业级大模型治理平台怎么选？"
    answer = adapter.answer(prompt, SimpleNamespace(), SimpleNamespace(), [])
    assert captured["path"].endswith("/services/aigc/text-generation/generation")
    assert captured["payload"]["input"]["messages"] == [{"role": "user", "content": prompt}]
    options = captured["payload"]["parameters"]["search_options"]
    assert options["forced_search"] is True
    assert options["enable_source"] is True
    assert answer.search_verified is True
    assert answer.source_items[0]["url"] == "https://example.com/qwen-report"
    return {"sources": len(answer.source_items), "gate": answer.search_verification["gate"]}


def verify_bailian_qwen_responses() -> dict:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={
            "id": "resp_qwen_contract",
            "object": "response",
            "status": "completed",
            "output": [
                {
                    "id": "search_1",
                    "type": "web_search_call",
                    "status": "completed",
                    "action": {"sources": [{
                        "title": "百炼新人免费额度",
                        "url": "https://example.com/bailian-free-tier",
                    }]},
                },
                {"id": "msg_1", "type": "message", "role": "assistant", "content": [{
                    "type": "output_text",
                    "text": "建议比较模型能力、联网来源与成本。",
                    "annotations": [{
                        "type": "url_citation",
                        "title": "百炼新人免费额度",
                        "url": "https://example.com/bailian-free-tier",
                    }],
                }]},
            ],
        })

    adapter = BailianQwenResponsesProvider(
        provider("bailian_qwen_responses", "qwen3.7-plus", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        api_key="test-only",
        transport=httpx.MockTransport(handler),
    )
    answer = adapter.answer("企业级大模型治理平台怎么选？", SimpleNamespace(), SimpleNamespace(), [])
    assert captured["path"].endswith("/responses")
    assert captured["payload"]["model"] == "qwen3.7-plus"
    assert captured["payload"]["tools"] == [{"type": "web_search"}]
    assert answer.search_verified is True
    assert answer.source_items[0]["url"] == "https://example.com/bailian-free-tier"
    return {"sources": len(answer.source_items), "gate": answer.search_verification["gate"]}


def verify_bailian_arrearage() -> dict:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={
            "code": "Arrearage",
            "message": "Access denied, please make sure your account is in good standing.",
            "request_id": "qwen-arrearage-contract",
        })

    adapter = BailianQwenResponsesProvider(
        provider("bailian_qwen_responses", "qwen3.7-plus", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        api_key="test-only",
        transport=httpx.MockTransport(handler),
    )
    try:
        adapter.answer("企业级大模型治理平台怎么选？", SimpleNamespace(), SimpleNamespace(), [])
    except ValueError as exc:
        message = str(exc)
        assert "账户欠费或账单状态异常" in message
        assert "qwen-arrearage-contract" in message
        return {"safe_error": "Arrearage translated with recovery guidance and request id"}
    raise AssertionError("Arrearage must reject the provider test")


def verify_kimi() -> dict:
    captured_messages: list[list[dict]] = []
    chat_round = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal chat_round
        path = request.url.path
        if request.method == "GET" and path.endswith("/tools"):
            return httpx.Response(200, json={"tools": [{
                "type": "function",
                "function": {"name": "web_search", "parameters": {"type": "object"}},
            }]})
        if path.endswith("/fibers"):
            payload = json.loads(request.content)
            assert payload["name"] == "web_search"
            return httpx.Response(200, json={"context": {"output": json.dumps({
                "results": [{"title": "治理平台选型报告", "url": "https://example.com/kimi-report"}]
            })}})
        if path.endswith("/chat/completions"):
            payload = json.loads(request.content)
            captured_messages.append(payload["messages"])
            chat_round += 1
            if chat_round == 1:
                return httpx.Response(200, json={"choices": [{"message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "web_search", "arguments": "{\"query\":\"治理平台选型\"}"},
                    }],
                }}]})
            return httpx.Response(200, json={"choices": [{"message": {
                "role": "assistant",
                "content": "建议从合规审计、模型覆盖与私有化交付三方面比较。",
            }}]})
        raise AssertionError(f"Unexpected Kimi path: {request.method} {path}")

    adapter = KimiWebSearchProvider(
        provider("kimi_web_search", "kimi-k3", "https://api.moonshot.cn/v1"),
        api_key="test-only",
        transport=httpx.MockTransport(handler),
    )
    prompt = "企业级大模型治理平台怎么选？"
    answer = adapter.answer(prompt, SimpleNamespace(), SimpleNamespace(), [])
    assert captured_messages[0] == [{"role": "user", "content": prompt}]
    assert captured_messages[1][-1]["role"] == "tool"
    assert answer.search_verified is True
    assert answer.source_items[0]["url"] == "https://example.com/kimi-report"
    return {"sources": len(answer.source_items), "gate": answer.search_verification["gate"]}


def verify_deepseek() -> dict:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={
            "content": [
                {"type": "server_tool_use", "name": "web_search", "id": "search_1"},
                {"type": "web_search_tool_result", "tool_use_id": "search_1", "content": [{
                    "title": "治理平台选型报告",
                    "url": "https://example.com/deepseek-report",
                }]},
                {"type": "text", "text": "建议比较审计、权限和部署方式。", "citations": [{
                    "title": "治理平台选型报告",
                    "url": "https://example.com/deepseek-report",
                }]},
            ]
        })

    adapter = DeepSeekWebSearchProvider(
        provider("deepseek_web_search", "deepseek-v4-flash", "https://api.deepseek.com"),
        api_key="test-only",
        transport=httpx.MockTransport(handler),
    )
    answer = adapter.answer("企业级大模型治理平台怎么选？", SimpleNamespace(), SimpleNamespace(), [])
    assert captured["path"] == "/anthropic/v1/messages"
    assert captured["payload"]["tools"][0]["name"] == "web_search"
    assert answer.search_verified is True
    assert answer.source_items[0]["url"] == "https://example.com/deepseek-report"
    return {"sources": len(answer.source_items), "gate": answer.search_verification["gate"]}


def verify_hunyuan() -> dict:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={
            "choices": [{"message": {
                "role": "assistant",
                "content": "建议比较合规审计、权限体系和私有化能力。[1]",
                "search_info": [{
                    "title": "企业模型治理研究",
                    "url": "https://example.com/hunyuan-report",
                }],
            }}]
        })

    adapter = HunyuanWebSearchProvider(
        provider("hunyuan_web_search", "hunyuan-turbos-latest", "https://api.hunyuan.cloud.tencent.com/v1"),
        api_key="test-only",
        transport=httpx.MockTransport(handler),
    )
    answer = adapter.answer("企业级大模型治理平台怎么选？", SimpleNamespace(), SimpleNamespace(), [])
    assert captured["path"].endswith("/chat/completions")
    assert captured["payload"]["enable_enhancement"] is True
    assert captured["payload"]["force_search_enhancement"] is True
    assert captured["payload"]["search_info"] is True
    assert captured["payload"]["citation"] is True
    assert answer.search_verified is True
    assert answer.source_items[0]["url"] == "https://example.com/hunyuan-report"
    return {"sources": len(answer.source_items), "gate": answer.search_verification["gate"]}


def verify_doubao() -> dict:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={
            "id": "resp_doubao_contract",
            "object": "response",
            "status": "completed",
            "output": [
                {
                    "id": "ws_1",
                    "type": "web_search_call",
                    "status": "completed",
                    "action": {
                        "type": "search",
                        "sources": [{
                            "title": "企业大模型治理选型报告",
                            "url": "https://example.com/doubao-report",
                        }],
                    },
                },
                {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "content": [{
                        "type": "output_text",
                        "text": "建议比较审计能力、权限模型、私有化部署与真实客户案例。",
                        "annotations": [{
                            "type": "url_citation",
                            "title": "企业大模型治理选型报告",
                            "url": "https://example.com/doubao-report",
                        }],
                    }],
                },
            ],
        })

    adapter = VolcengineWebSearchProvider(
        provider("volcengine_ark", "doubao-seed-2-0-lite-260215", "https://ark.cn-beijing.volces.com/api/v3"),
        api_key="test-only",
        transport=httpx.MockTransport(handler),
    )
    prompt = "企业级大模型治理平台怎么选？"
    answer = adapter.answer(prompt, SimpleNamespace(), SimpleNamespace(), [])
    assert captured["path"].endswith("/responses")
    assert captured["payload"]["input"] == prompt
    assert captured["payload"]["tools"] == [{"type": "web_search"}]
    assert captured["payload"]["thinking"] == {"type": "disabled"}
    assert captured["payload"]["store"] is False
    assert answer.search_verified is True
    assert answer.source_items[0]["url"] == "https://example.com/doubao-report"
    return {"sources": len(answer.source_items), "gate": answer.search_verification["gate"]}


def verify_doubao_tool_not_open() -> dict:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            headers={"x-request-id": "doubao-tool-not-open"},
            json={"error": {
                "code": "ToolNotOpen",
                "message": "Your account has not activated web search.",
                "type": "NotFound",
            }},
        )

    adapter = VolcengineWebSearchProvider(
        provider("volcengine_ark", "doubao-seed-2-1-pro-260628", "https://ark.cn-beijing.volces.com/api/v3"),
        api_key="test-only",
        transport=httpx.MockTransport(handler),
    )
    try:
        adapter.answer("企业级大模型治理平台怎么选？", SimpleNamespace(), SimpleNamespace(), [])
    except ValueError as exc:
        message = str(exc)
        assert "Web Search 插件尚未开通" in message
        assert "doubao-tool-not-open" in message
        return {"safe_error": "ToolNotOpen translated with activation URL and request id"}
    raise AssertionError("ToolNotOpen must reject the provider test")


def main() -> None:
    print(json.dumps({
        "ok": True,
        "qwen": verify_qwen(),
        "bailian_qwen_responses": verify_bailian_qwen_responses(),
        "bailian_arrearage": verify_bailian_arrearage(),
        "kimi": verify_kimi(),
        "deepseek": verify_deepseek(),
        "hunyuan": verify_hunyuan(),
        "doubao": verify_doubao(),
        "doubao_tool_not_open": verify_doubao_tool_not_open(),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
