from dataclasses import dataclass, field
import json
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.config import get_settings
from app.models import Company, Competitor, LLMProvider, Project
from app.services.workspace_secrets import decrypt_secret


DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "openai_compatible": "https://api.openai.com/v1",
    "deepseek_web_search": "https://api.deepseek.com/anthropic",
    "kimi_web_search": "https://api.moonshot.ai/v1",
    "hunyuan_web_search": "https://api.hunyuan.cloud.tencent.com/v1",
    "volcengine_ark": "https://ark.cn-beijing.volces.com/api/v3",
    "qwen_compatible": "https://dashscope.aliyuncs.com/api/v1",
    "bailian_qwen_responses": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "xiaoma_domestic_web_search": "https://api.lingkeai.ai/v1",
    "browser_observation": "https://www.doubao.com",
}

DEFAULT_CHAT_COMPLETION_TIMEOUT_SECONDS = 180.0


def _provider_http_timeout(timeout_seconds: float) -> httpx.Timeout:
    """Keep connection failures fast while allowing real search providers to finish."""
    read_timeout = max(30.0, min(float(timeout_seconds), 180.0))
    return httpx.Timeout(read_timeout, connect=min(10.0, read_timeout), write=30.0, pool=10.0)

ENV_KEY_BY_PROVIDER_TYPE = {
    "openai": "OPENAI_API_KEY",
    "openai_compatible": "OPENAI_API_KEY",
    "deepseek_web_search": "DEEPSEEK_API_KEY",
    "kimi_web_search": "KIMI_API_KEY",
    "hunyuan_web_search": "HUNYUAN_API_KEY",
    "volcengine_ark": "ARK_API_KEY",
    "qwen_compatible": "QWEN_API_KEY",
    "bailian_qwen_responses": "DASHSCOPE_API_KEY",
    "xiaoma_domestic_web_search": "XIAOMA_API_KEY",
}


def _raise_provider_http_error(response: httpx.Response, *, provider_label: str) -> None:
    """Raise a useful, secret-safe provider error instead of losing the response body."""
    if not response.is_error:
        return
    code = ""
    message = ""
    error_type = ""
    request_id = ""
    try:
        payload = response.json()
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            code = str(error.get("code") or "").strip()
            message = str(error.get("message") or "").strip()
            error_type = str(error.get("type") or "").strip()
        elif isinstance(payload, dict):
            code = str(payload.get("code") or "").strip()
            message = str(payload.get("message") or "").strip()
            error_type = str(payload.get("type") or "").strip()
            request_id = str(payload.get("request_id") or payload.get("requestId") or "").strip()
    except (ValueError, TypeError):
        pass
    request_id = request_id or str(response.headers.get("x-request-id") or "").strip()
    if code == "ToolNotOpen" and provider_label == "火山方舟":
        raise ValueError(
            "火山方舟 Web Search 插件尚未开通。请前往 "
            "https://console.volcengine.com/common-buy/CC_content_plugin 开通联网内容插件；"
            f"开通后重新验证。请求 ID：{request_id or '未返回'}"
        )
    if code == "Arrearage" and provider_label == "阿里云百炼":
        raise ValueError(
            "阿里云百炼账户欠费或账单状态异常。即使仍有免费模型 Token，账户欠费时也会拒绝联网调用；"
            f"请先在费用中心恢复正常状态后重试。请求 ID：{request_id or '未返回'}"
        )
    detail = message or f"HTTP {response.status_code}"
    metadata = " / ".join(item for item in (code, error_type, request_id) if item)
    if metadata:
        detail = f"{detail}（{metadata}）"
    raise ValueError(f"{provider_label} 请求失败：{detail}")

PROVIDER_ONBOARDING = [
    {
        "provider_type": "deepseek_web_search",
        "platform_key": "deepseek",
        "label": "DeepSeek 官方 API + Web Search",
        "default_base_url": DEFAULT_BASE_URLS["deepseek_web_search"],
        "template_name": "DeepSeek 官方联网 GEO 采集",
        "template_base_url": DEFAULT_BASE_URLS["deepseek_web_search"],
        "template_model_name": "deepseek-v4-flash",
        "model_examples": ["deepseek-v4-pro", "deepseek-v4-flash"],
        "auth_env": ENV_KEY_BY_PROVIDER_TYPE["deepseek_web_search"],
        "access_method": "official_api_with_web_search",
        "search_mode": "provider_web_search",
        "supports_web_search": True,
        "collection_fit": "通过 DeepSeek 官方 Anthropic 兼容接口调用 Web Search，保留搜索结果、回答和引用证据。",
        "setup_steps": [
            "在 DeepSeek 开放平台创建 API Key，并配置 DEEPSEEK_API_KEY 或 Provider 级 Key。",
            "先运行一个不含品牌词的采购问题，确认响应包含 web_search_tool_result。",
            "只有搜索证据和回答同时存在时，结果才进入决策地图。",
        ],
        "caveats": ["API 搜索链可复现、可审计，但不能宣称与消费级网页端排序完全一致。"],
    },
    {
        "provider_type": "openai_compatible",
        "label": "OpenAI-compatible / API 中转站",
        "default_base_url": DEFAULT_BASE_URLS["openai_compatible"],
        "template_name": "API 中转站 GEO 采集",
        "template_base_url": "https://ccdan.cc.cd/v1",
        "template_model_name": "gpt-4o-mini",
        "model_examples": ["gpt-4o-mini", "gpt-4.1-mini", "中转站提供的模型名"],
        "auth_env": ENV_KEY_BY_PROVIDER_TYPE["openai_compatible"],
        "access_method": "chat_completion_api",
        "search_mode": "llm_answer_without_live_web",
        "supports_web_search": False,
        "collection_fit": "适合稳定采集普通大模型回答；是否联网取决于中转站和模型本身。",
        "setup_steps": [
            "Base URL 填到 /v1，例如 https://ccdan.cc.cd/v1。",
            "填写中转站支持的模型名称，并配置 API Key。",
            "先在后台完成一次测试调用，成功后再加入项目采集。",
        ],
        "caveats": [
            "普通 Chat Completions 不能保证复现网页端搜索结果。",
            "如果目标是抓“AI 搜索”答案，应优先选择明确带联网搜索能力的 Provider。",
        ],
    },
    {
        "provider_type": "kimi_web_search",
        "label": "Kimi Web Search",
        "default_base_url": DEFAULT_BASE_URLS["kimi_web_search"],
        "template_name": "Kimi 联网搜索 GEO 采集",
        "template_base_url": DEFAULT_BASE_URLS["kimi_web_search"],
        "template_model_name": "kimi-k3",
        "model_examples": ["kimi-k3", "kimi-k2.6", "kimi-k2.5"],
        "auth_env": ENV_KEY_BY_PROVIDER_TYPE["kimi_web_search"],
        "access_method": "builtin_web_search_api",
        "search_mode": "live_web_search",
        "supports_web_search": True,
        "collection_fit": "适合采集带来源线索的联网搜索回答，是第一版真实 GEO 监测优先渠道。",
        "setup_steps": [
            "配置 KIMI_API_KEY 或 Provider 级 API Key。",
            "Base URL 可留空使用 Kimi API 官方工具通道。",
            "系统会实际执行 moonshot/web-search:latest；没有来源 URL 时验证失败。",
        ],
        "caveats": ["需要确认账号和模型支持 builtin_function.$web_search。"],
    },
    {
        "provider_type": "hunyuan_web_search",
        "platform_key": "hunyuan",
        "label": "腾讯混元官方 API + 搜索增强",
        "default_base_url": DEFAULT_BASE_URLS["hunyuan_web_search"],
        "template_name": "腾讯混元官方联网 GEO 采集",
        "template_base_url": DEFAULT_BASE_URLS["hunyuan_web_search"],
        "template_model_name": "hunyuan-turbos-latest",
        "model_examples": ["hunyuan-turbos-latest", "hunyuan-large"],
        "auth_env": ENV_KEY_BY_PROVIDER_TYPE["hunyuan_web_search"],
        "access_method": "official_api_with_web_search",
        "search_mode": "hunyuan_forced_search_enhancement",
        "supports_web_search": True,
        "collection_fit": "通过腾讯混元 OpenAI 兼容接口强制开启搜索增强，保存 search_info、引用链接与完整回答。",
        "setup_steps": [
            "配置 HUNYUAN_API_KEY 或 Provider 级 API Key。",
            "使用支持搜索增强的模型，系统固定开启 enable_enhancement、force_search_enhancement、search_info 和 citation。",
            "没有 search_info 来源 URL 或最终回答时拒绝进入决策地图。",
        ],
        "caveats": ["hunyuan-lite 不支持搜索增强；官方 API 结果不等同于消费级网页端个性化排序。"],
    },
    {
        "provider_type": "volcengine_ark",
        "platform_key": "doubao",
        "label": "豆包官方 API + Web Search",
        "default_base_url": DEFAULT_BASE_URLS["volcengine_ark"],
        "template_name": "豆包官方联网 GEO 采集",
        "template_base_url": DEFAULT_BASE_URLS["volcengine_ark"],
        "template_model_name": "doubao-seed-2-1-pro-260628",
        "model_examples": [
            "doubao-seed-2-1-pro-260628",
            "doubao-seed-2-1-turbo-260628",
            "火山方舟支持 Responses API 与 Web Search 的模型 ID",
        ],
        "auth_env": ENV_KEY_BY_PROVIDER_TYPE["volcengine_ark"],
        "access_method": "official_api_with_web_search",
        "search_mode": "ark_responses_web_search",
        "supports_web_search": True,
        "collection_fit": "通过火山方舟 Responses API 调用豆包内置 Web Search，保存搜索事件、来源和最终回答。",
        "setup_steps": [
            "配置 ARK_API_KEY 或 Provider 级 API Key。",
            "默认使用已开通的 Doubao Seed 2.1 Pro；账号免费额度存在时会优先消耗免费额度。",
            "系统会调用 /responses 并声明 web_search；没有搜索事件或来源 URL 时验证失败。",
        ],
        "caveats": [
            "官方 API 联网链可审计，但不包含豆包消费级网页账号的记忆和个性化排序。",
            "免费额度由火山方舟账号侧决定；系统无法替代控制台确认剩余额度。",
        ],
    },
    {
        "provider_type": "volcengine_ark",
        "platform_key": "glm",
        "label": "智谱 GLM 官方 API + Web Search",
        "default_base_url": DEFAULT_BASE_URLS["volcengine_ark"],
        "template_name": "智谱 GLM 官方联网 GEO 采集",
        "template_base_url": DEFAULT_BASE_URLS["volcengine_ark"],
        "template_model_name": "glm-5-2-260617",
        "model_examples": ["glm-5-2-260617", "火山方舟支持 Responses API 与 Web Search 的 GLM 模型 ID"],
        "auth_env": ENV_KEY_BY_PROVIDER_TYPE["volcengine_ark"],
        "access_method": "official_api_with_web_search",
        "search_mode": "ark_responses_web_search",
        "supports_web_search": True,
        "collection_fit": "通过火山方舟 Responses API 调用 GLM 内置 Web Search，保存搜索事件、来源和最终回答。",
        "setup_steps": [
            "配置 ARK_API_KEY 或 Provider 级 API Key。",
            "在火山方舟确认 GLM 模型已开通 Responses API 与 Web Search。",
            "系统会调用 /responses 并声明 web_search；没有搜索事件或来源 URL 时验证失败。",
        ],
        "caveats": ["官方 API 联网链可审计，但不等同于消费级产品的个性化排序。"],
    },
    {
        "provider_type": "bailian_qwen_responses",
        "platform_key": "qianwen",
        "label": "通义千问 3.7 Plus · 百炼官方 API + Web Search",
        "default_base_url": DEFAULT_BASE_URLS["bailian_qwen_responses"],
        "template_name": "千问 3.7 Plus 官方联网 GEO 采集",
        "template_base_url": DEFAULT_BASE_URLS["bailian_qwen_responses"],
        "template_model_name": "qwen3.7-plus",
        "model_examples": ["qwen3.7-plus", "qwen3.7-max"],
        "auth_env": ENV_KEY_BY_PROVIDER_TYPE["bailian_qwen_responses"],
        "access_method": "official_responses_api_with_web_search",
        "search_mode": "qwen_responses_web_search",
        "supports_web_search": True,
        "collection_fit": "通过百炼官方 Responses API 固定声明 web_search；只有搜索调用、来源 URL 和最终回答齐全才归档。",
        "setup_steps": [
            "配置 DASHSCOPE_API_KEY 或 Provider 级 API Key。",
            "默认模型 qwen3.7-plus；它可作为千问的免费额度主采样模型。",
            "系统调用 /responses 并固定 tools: [{type: web_search}]；缺少搜索事件或来源 URL 时验证失败。",
        ],
        "caveats": ["这是百炼官方联网回答链，不等同于消费级千问网页账号的记忆、个性化或界面排序。"],
    },
    {
        "provider_type": "qwen_compatible",
        "label": "千问兼容",
        "default_base_url": DEFAULT_BASE_URLS["qwen_compatible"],
        "template_name": "千问兼容 GEO 采集",
        "template_base_url": DEFAULT_BASE_URLS["qwen_compatible"],
        "template_model_name": "qwen-plus",
        "model_examples": ["qwen-plus", "qwen-max"],
        "auth_env": ENV_KEY_BY_PROVIDER_TYPE["qwen_compatible"],
        "access_method": "chat_completion_api",
        "search_mode": "llm_answer_without_live_web",
        "supports_web_search": True,
        "collection_fit": "通过百炼 DashScope 原生接口强制联网，返回 search_info、引用标记和原始来源。",
        "setup_steps": [
            "配置 QWEN_API_KEY、DASHSCOPE_API_KEY 或 Provider 级 API Key。",
            "Base URL 可留空使用 DashScope 原生 API；业务空间可填写对应的 /api/v1 地址。",
            "系统固定 forced_search=true、enable_source=true；缺少 search_info 时拒绝入库。",
        ],
        "caveats": ["这是千问官方模型联网链，不宣称与消费级网页端的个性化排序完全相同。"],
    },
    {
        "provider_type": "xiaoma_domestic_web_search",
        "label": "小马 API · 国内模型联网搜索",
        "default_base_url": DEFAULT_BASE_URLS["xiaoma_domestic_web_search"],
        "template_name": "小马 API · 千问 3.5 Plus 联网采集",
        "template_base_url": DEFAULT_BASE_URLS["xiaoma_domestic_web_search"],
        "template_model_name": "qwen3.5-plus",
        "model_examples": [
            "qwen3.5-plus", "qwen3.6-plus", "qwen3.7-plus", "qwen3.7-max",
            "kimi-k3", "deepseek-v4-pro", "doubao-seed-2-1-pro-260628", "glm-5.2",
        ],
        "auth_env": ENV_KEY_BY_PROVIDER_TYPE["xiaoma_domestic_web_search"],
        "access_method": "aggregate_api_with_web_search",
        "search_mode": "responses_web_search",
        "supports_web_search": True,
        "collection_fit": "通过小马聚合 Responses API 强制声明 web_search；只有搜索事件、来源 URL 和最终回答同时存在时才归档。",
        "setup_steps": [
            "配置小马 API Key，并从 GET /v1/models 返回的授权模型中选择模型名。",
            "系统固定发送 tools: [{type: web_search}]，并校验 web_search_call、来源 URL 和最终回答。",
            "每个模型都必须单独通过联网测试；未通过的模型不会进入决策地图。",
        ],
        "caveats": [
            "这是聚合 API，不等同于千问、Kimi、DeepSeek 或豆包的官方直连。",
            "聚合渠道的模型路由、搜索索引和稳定性可能变动，应保留原始响应并持续复测。",
        ],
    },
    {
        "provider_type": "browser_observation",
        "label": "浏览器网页端观测",
        "default_base_url": DEFAULT_BASE_URLS["browser_observation"],
        "template_name": "豆包网页端 GEO 观测",
        "template_base_url": DEFAULT_BASE_URLS["browser_observation"],
        "template_model_name": "browser-observation",
        "model_examples": ["doubao-web", "deepseek-web", "yuanbao-web", "kimi-web"],
        "auth_env": None,
        "access_method": "browser_automation",
        "search_mode": "web_ui_observation",
        "supports_web_search": True,
        "collection_fit": "适合抽样观测网页端真实回答、保存截图和人工核验；不适合作为每小时高频生产采集主链路。",
        "setup_steps": [
            "配置网页入口 URL，例如豆包、DeepSeek、元宝或 Kimi 的网页端地址。",
            "使用浏览器自动化或人工辅助登录，先做低频抽样验证。",
            "记录答案文本、截图、时间和账号状态，作为真实网页端观测证据。",
        ],
        "caveats": [
            "网页端可能有登录、验证码、风控和使用条款限制。",
            "免费额度适合验证，不适合承诺长期高频商业采集。",
        ],
    },
    {
        "provider_type": "mock",
        "label": "Mock 演示",
        "default_base_url": None,
        "template_name": "Mock GEO 演示采集",
        "template_base_url": None,
        "template_model_name": "mock-geo-search",
        "model_examples": ["mock-geo-search"],
        "auth_env": None,
        "access_method": "mock",
        "search_mode": "mock_simulation",
        "supports_web_search": False,
        "collection_fit": "适合本地开发、演示和验收闭环；不能代表真实大模型搜索结果。",
        "setup_steps": ["保留用于开发演示；上线前至少配置一个真实 Provider 并测试成功。"],
        "caveats": ["Mock 结果不应用于真实客户报告。"],
    },
]


@dataclass
class ProviderAnswer:
    prompt_text: str
    raw_answer: str
    answer_summary: str
    source_items: list[dict[str, Any]] = field(default_factory=list)
    raw_provider_payload: dict[str, Any] = field(default_factory=dict)
    collection_method: str = "api"
    search_verified: bool = False
    search_event_count: int = 0
    search_verification: dict[str, Any] = field(default_factory=dict)


class BaseLLMSearchProvider:
    def answer(self, prompt_text: str, company: Company, project: Project, competitors: list[Competitor]) -> ProviderAnswer:
        raise NotImplementedError


class MockLLMSearchProvider(BaseLLMSearchProvider):
    def __init__(self, provider: LLMProvider):
        self.provider = provider

    def answer(self, prompt_text: str, company: Company, project: Project, competitors: list[Competitor]) -> ProviderAnswer:
        competitor_names = [item.name for item in competitors[:3]]
        competitor_text = "、".join(competitor_names) if competitor_names else "若干行业服务商"
        brand_alias = f"（也可能被称为{company.brand_aliases[0]}）" if company.brand_aliases else ""
        company_source = company.website_url or "https://example.com/solutions/geo"
        answer = (
            f"针对“{prompt_text}”，{self.provider.name} 的模拟答案会先推荐具备公开案例、"
            f"官网解决方案页、媒体报道和行业方法论沉淀的服务商。{company.name}{brand_alias}"
            f"可以作为候选之一，但当前公开信源需要进一步强化。竞品方面，{competitor_text}"
            "在答案中可能更容易被提到，因为它们通常有更多可被检索到的榜单、案例或评测内容。\n\n"
            "建议优先补充三类信源：官网 FAQ 与解决方案页、第三方媒体报道、结构化案例文章。"
            "这些内容应直接回答目标问题，包含清晰实体名、适用场景、服务能力、案例证据和总结性列表。\n\n"
            f"可参考的信源线索包括：{company_source} "
            "https://media.example.com/industry/security-training-ranking "
            "https://report.example.com/ai-search-geo-playbook"
        )
        return ProviderAnswer(
            prompt_text=prompt_text,
            raw_answer=answer,
            answer_summary=f"{company.name} 被提及为候选，竞品 {competitor_text} 也被提及。",
        )


class OpenAICompatibleSearchProvider(BaseLLMSearchProvider):
    def __init__(
        self,
        provider: LLMProvider,
        api_key: str | None = None,
        default_base_url: str = DEFAULT_BASE_URLS["openai_compatible"],
    ):
        self.provider = provider
        self.api_key = api_key or (provider.auth_config or {}).get("api_key")
        self.base_url = (provider.api_base_url or default_base_url).rstrip("/")
        self.timeout_seconds = float(
            provider.cost_rule.get("timeout_seconds") or DEFAULT_CHAT_COMPLETION_TIMEOUT_SECONDS
        )

    def answer(
        self, prompt_text: str, company: Company, project: Project, competitors: list[Competitor]
    ) -> ProviderAnswer:
        if not self.api_key:
            raise ValueError(f"Missing API key for provider {self.provider.name}")

        system_prompt = (
            "你是面向普通用户的企业软件选型助手。请根据问题本身自然作答，"
            "不要因为后台监测目标而优先提及任何企业或品牌。"
        )
        user_prompt = (
            f"{prompt_text}\n\n"
            "请直接回答。如果问题涉及产品或服务商选择，请按你掌握的公开信息列出候选对象、"
            "比较理由和可核验的公开信源；不知道时请明确说明，不要虚构品牌、案例或网址。"
        )
        payload = {
            "model": self.provider.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        if self.provider.provider_type == "volcengine_ark" and self.provider.cost_rule.get(
            "disable_thinking"
        ):
            payload["thinking"] = {"type": "disabled"}
        if self.provider.provider_type == "qwen_compatible" and self.provider.cost_rule.get("enable_search"):
            payload["extra_body"] = {"enable_search": True}
        max_attempts = max(1, min(int(self.provider.cost_rule.get("response_retry_attempts", 1) or 1), 3))
        last_error: Exception | None = None
        content = ""
        for _attempt in range(1, max_attempts + 1):
            try:
                with httpx.Client(timeout=_provider_http_timeout(self.timeout_seconds)) as client:
                    response = client.post(
                        f"{self.base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()
                choices = data.get("choices") if isinstance(data, dict) else None
                if not choices or not isinstance(choices[0], dict):
                    raise ValueError("Provider response did not contain a valid choices[0]")
                message = choices[0].get("message") or {}
                content = message.get("content") or ""
                if not content.strip():
                    raise ValueError("Provider response content was empty")
                break
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
                last_error = exc
        if not content:
            raise ValueError(f"Provider response failed after {max_attempts} attempts: {last_error}")
        return ProviderAnswer(
            prompt_text=prompt_text,
            raw_answer=content,
            answer_summary=content[:180],
        )


def _deepseek_search_sources(content_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for block in content_blocks:
        candidates: list[dict[str, Any]] = []
        if block.get("type") == "web_search_tool_result" and isinstance(block.get("content"), list):
            candidates.extend(item for item in block["content"] if isinstance(item, dict))
        if block.get("type") == "text" and isinstance(block.get("citations"), list):
            candidates.extend(item for item in block["citations"] if isinstance(item, dict))
        for item in candidates:
            url = item.get("url") or item.get("source_url")
            if not isinstance(url, str) or not url.startswith(("http://", "https://")) or url in seen:
                continue
            seen.add(url)
            sources.append(
                {
                    "number": len(sources) + 1,
                    "title": str(item.get("title") or item.get("name") or url),
                    "url": url,
                    "domain": urlsplit(url).hostname,
                    "page_age": item.get("page_age"),
                }
            )
    return sources


class DeepSeekWebSearchProvider(BaseLLMSearchProvider):
    """DeepSeek official Anthropic-compatible API with provider Web Search."""

    def __init__(
        self,
        provider: LLMProvider,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.provider = provider
        self.api_key = api_key or (provider.auth_config or {}).get("api_key")
        configured_base_url = (provider.api_base_url or DEFAULT_BASE_URLS["deepseek_web_search"]).rstrip("/")
        # The Web Search tool is exposed on DeepSeek's Anthropic-compatible surface.
        # Normalize a bare api.deepseek.com value saved by older UI versions.
        self.base_url = (
            f"{configured_base_url}/anthropic"
            if urlsplit(configured_base_url).hostname == "api.deepseek.com"
            and urlsplit(configured_base_url).path.rstrip("/") in {"", "/"}
            else configured_base_url
        )
        self.timeout_seconds = float(
            provider.cost_rule.get("timeout_seconds") or DEFAULT_CHAT_COMPLETION_TIMEOUT_SECONDS
        )
        self.transport = transport

    def answer(
        self, prompt_text: str, company: Company, project: Project, competitors: list[Competitor]
    ) -> ProviderAnswer:
        if not self.api_key:
            raise ValueError(f"Missing API key for provider {self.provider.name}")
        payload = {
            "model": self.provider.model_name or "deepseek-v4-flash",
            "max_tokens": int(self.provider.cost_rule.get("max_tokens") or 4096),
            "thinking": {"type": str(self.provider.cost_rule.get("thinking_type") or "disabled")},
            "output_config": {"effort": str(self.provider.cost_rule.get("reasoning_effort") or "low")},
            "system": (
                "你是面向普通企业采购者的选型助手。必须先使用联网搜索，再根据搜索证据自然回答。"
                "不要因为后台监测目标而优先提及任何品牌；不知道时明确说明，不得虚构来源。"
            ),
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt_text}]}],
            "tools": [
                {
                    "type": str(self.provider.cost_rule.get("web_search_tool_type") or "web_search_20250305"),
                    "name": "web_search",
                    "max_uses": int(self.provider.cost_rule.get("web_search_max_uses") or 4),
                }
            ],
        }
        with httpx.Client(
            timeout=_provider_http_timeout(self.timeout_seconds),
            transport=self.transport,
        ) as client:
            response = client.post(
                f"{self.base_url}/v1/messages",
                headers={
                    "x-api-key": str(self.api_key),
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )
            _raise_provider_http_error(response, provider_label="DeepSeek")
            data = response.json()
        blocks = data.get("content") if isinstance(data, dict) else None
        if not isinstance(blocks, list):
            raise ValueError("DeepSeek response did not contain content blocks")
        typed_blocks = [item for item in blocks if isinstance(item, dict)]
        search_calls = [
            item for item in typed_blocks
            if item.get("type") == "server_tool_use" and item.get("name") == "web_search"
        ]
        search_results = [item for item in typed_blocks if item.get("type") == "web_search_tool_result"]
        answer_text = "\n\n".join(
            str(item.get("text") or "").strip()
            for item in typed_blocks
            if item.get("type") == "text" and str(item.get("text") or "").strip()
        )
        sources = _deepseek_search_sources(typed_blocks)
        if not answer_text:
            raise ValueError("DeepSeek Web Search returned no final answer")
        if not search_calls or not search_results:
            raise ValueError("DeepSeek response did not prove a completed Web Search tool call")
        if not sources:
            raise ValueError("DeepSeek API returned no auditable web_search_tool_result")
        return ProviderAnswer(
            prompt_text=prompt_text,
            raw_answer=answer_text,
            answer_summary=answer_text[:180],
            source_items=sources,
            raw_provider_payload=data,
            collection_method="official_api_web_search",
            search_verified=True,
            search_event_count=len(search_calls) + len(search_results),
            search_verification={
                "gate": "server_tool_use:web_search + web_search_tool_result + sources",
                "web_search_call_count": len(search_calls),
                "web_search_result_block_count": len(search_results),
                "source_count": len(sources),
            },
        )


def _source_items_from_nested_payload(payload: Any) -> list[dict[str, Any]]:
    """Extract auditable web URLs without treating arbitrary answer text as proof."""

    sources: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            url = value.get("url") or value.get("href") or value.get("source_url")
            if isinstance(url, str) and url.startswith(("http://", "https://")) and url not in seen:
                seen.add(url)
                sources.append({
                    "number": len(sources) + 1,
                    "title": str(value.get("title") or value.get("name") or value.get("site_name") or url),
                    "url": url,
                    "domain": urlsplit(url).hostname,
                    "site_name": value.get("site_name"),
                    "published_at": value.get("publish_time") or value.get("date"),
                })
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)
        elif isinstance(value, str) and value.lstrip().startswith(("{", "[")):
            try:
                visit(json.loads(value))
            except json.JSONDecodeError:
                pass

    visit(payload)
    return sources


class KimiWebSearchProvider(BaseLLMSearchProvider):
    """Kimi official Formula API web-search chain with a hard evidence gate."""

    FORMULA_URI = "moonshot/web-search:latest"

    def __init__(
        self,
        provider: LLMProvider,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.provider = provider
        self.api_key = api_key or (provider.auth_config or {}).get("api_key")
        self.base_url = (provider.api_base_url or DEFAULT_BASE_URLS["kimi_web_search"]).rstrip("/")
        self.timeout_seconds = float(
            provider.cost_rule.get("timeout_seconds") or DEFAULT_CHAT_COMPLETION_TIMEOUT_SECONDS
        )
        self.transport = transport

    def answer(
        self, prompt_text: str, company: Company, project: Project, competitors: list[Competitor]
    ) -> ProviderAnswer:
        if not self.api_key:
            raise ValueError(f"Missing API key for provider {self.provider.name}")

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt_text}]
        raw_rounds: list[dict[str, Any]] = []
        raw_fibers: list[dict[str, Any]] = []
        search_call_count = 0
        answer_text = ""

        with httpx.Client(
            timeout=_provider_http_timeout(self.timeout_seconds),
            transport=self.transport,
        ) as client:
            tool_response = client.get(
                f"{self.base_url}/formulas/{self.FORMULA_URI}/tools",
                headers=headers,
            )
            tool_response.raise_for_status()
            tool_payload = tool_response.json()
            tools = tool_payload.get("tools") if isinstance(tool_payload, dict) else None
            if not isinstance(tools, list) or not tools:
                raise ValueError("Kimi Formula API did not return web-search tool declarations")

            for _round in range(6):
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json={
                        "model": self.provider.model_name or "kimi-k3",
                        "messages": messages,
                        "tools": tools,
                        "reasoning_effort": str(self.provider.cost_rule.get("reasoning_effort") or "low"),
                    },
                )
                response.raise_for_status()
                data = response.json()
                raw_rounds.append(data)
                choices = data.get("choices") if isinstance(data, dict) else None
                if not choices or not isinstance(choices[0], dict):
                    raise ValueError("Kimi response did not contain choices[0]")
                message = choices[0].get("message") or {}
                tool_calls = message.get("tool_calls") or []
                if not tool_calls:
                    answer_text = str(message.get("content") or "").strip()
                    break
                messages.append({key: value for key, value in message.items() if key in {"role", "content", "tool_calls"}})
                for tool_call in tool_calls:
                    function = tool_call.get("function") or {}
                    fiber_response = client.post(
                        f"{self.base_url}/formulas/{self.FORMULA_URI}/fibers",
                        headers=headers,
                        json={"name": function.get("name"), "arguments": function.get("arguments")},
                    )
                    fiber_response.raise_for_status()
                    fiber = fiber_response.json()
                    raw_fibers.append(fiber)
                    search_call_count += 1
                    context = fiber.get("context") if isinstance(fiber, dict) else {}
                    result = (context or {}).get("output") or (context or {}).get("encrypted_output") or ""
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.get("id"),
                        "name": function.get("name"),
                        "content": result if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
                    })

        sources = _source_items_from_nested_payload(raw_fibers)
        if search_call_count < 1:
            raise ValueError("Kimi did not execute the official web-search tool")
        if not sources:
            raise ValueError("Kimi web search returned no auditable source URLs")
        if not answer_text:
            raise ValueError("Kimi web search did not return a final answer")
        raw_payload = {"tools": tool_payload, "rounds": raw_rounds, "fibers": raw_fibers}
        return ProviderAnswer(
            prompt_text=prompt_text,
            raw_answer=answer_text,
            answer_summary=answer_text[:180],
            source_items=sources,
            raw_provider_payload=raw_payload,
            collection_method="official_api_web_search",
            search_verified=True,
            search_event_count=search_call_count + 1,
            search_verification={
                "gate": "formula tool call + fiber output + source URLs + final answer",
                "formula_uri": self.FORMULA_URI,
                "web_search_call_count": search_call_count,
                "source_count": len(sources),
            },
        )


def _nested_values_for_key(payload: Any, key: str) -> list[Any]:
    values: list[Any] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for item_key, nested in value.items():
                if item_key == key:
                    values.append(nested)
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(payload)
    return values


class HunyuanWebSearchProvider(BaseLLMSearchProvider):
    """Tencent Hunyuan OpenAI-compatible API with forced search evidence."""

    def __init__(
        self,
        provider: LLMProvider,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.provider = provider
        self.api_key = api_key or (provider.auth_config or {}).get("api_key")
        self.base_url = (provider.api_base_url or DEFAULT_BASE_URLS["hunyuan_web_search"]).rstrip("/")
        self.timeout_seconds = float(
            provider.cost_rule.get("timeout_seconds") or DEFAULT_CHAT_COMPLETION_TIMEOUT_SECONDS
        )
        self.transport = transport

    def answer(
        self, prompt_text: str, company: Company, project: Project, competitors: list[Competitor]
    ) -> ProviderAnswer:
        if not self.api_key:
            raise ValueError(f"Missing API key for provider {self.provider.name}")
        payload = {
            "model": self.provider.model_name or "hunyuan-turbos-latest",
            "messages": [{"role": "user", "content": prompt_text}],
            "stream": False,
            "enable_enhancement": True,
            "force_search_enhancement": True,
            "search_info": True,
            "citation": True,
        }
        with httpx.Client(
            timeout=_provider_http_timeout(self.timeout_seconds),
            transport=self.transport,
            trust_env=False,
        ) as client:
            response = client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            _raise_provider_http_error(response, provider_label="腾讯混元")
            data = response.json()
        choices = data.get("choices") if isinstance(data, dict) else None
        if not choices or not isinstance(choices[0], dict):
            raise ValueError("腾讯混元响应缺少 choices[0]")
        message = choices[0].get("message") or {}
        answer_text = str(message.get("content") or "").strip()
        search_info_values = _nested_values_for_key(data, "search_info")
        sources = _source_items_from_nested_payload(search_info_values)
        if not search_info_values:
            raise ValueError("腾讯混元未返回 search_info，无法证明搜索增强已经执行")
        if not sources:
            raise ValueError("腾讯混元搜索增强未返回可审计来源 URL")
        if not answer_text:
            raise ValueError("腾讯混元搜索增强未返回最终回答")
        return ProviderAnswer(
            prompt_text=prompt_text,
            raw_answer=answer_text,
            answer_summary=answer_text[:180],
            source_items=sources,
            raw_provider_payload=data,
            collection_method="official_api_web_search",
            search_verified=True,
            search_event_count=1,
            search_verification={
                "gate": "forced search enhancement + search_info URLs + final answer",
                "force_search_enhancement": True,
                "search_info_block_count": len(search_info_values),
                "source_count": len(sources),
            },
        )


class VolcengineWebSearchProvider(BaseLLMSearchProvider):
    """Volcengine Ark Responses API with an evidence-enforced Web Search gate."""

    provider_label = "火山方舟"
    collection_method = "official_api_web_search"

    def __init__(
        self,
        provider: LLMProvider,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.provider = provider
        self.api_key = api_key or (provider.auth_config or {}).get("api_key")
        self.base_url = (provider.api_base_url or DEFAULT_BASE_URLS["volcengine_ark"]).rstrip("/")
        self.timeout_seconds = float(
            provider.cost_rule.get("timeout_seconds") or DEFAULT_CHAT_COMPLETION_TIMEOUT_SECONDS
        )
        self.transport = transport

    @staticmethod
    def _answer_text(payload: dict[str, Any]) -> str:
        blocks: list[str] = []
        output = payload.get("output")
        if not isinstance(output, list):
            return ""
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") in {"output_text", "text"}:
                    text = str(part.get("text") or "").strip()
                    if text:
                        blocks.append(text)
        return "\n\n".join(blocks)

    @staticmethod
    def _search_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
        output = payload.get("output")
        if not isinstance(output, list):
            return []
        return [
            item for item in output
            if isinstance(item, dict) and "web_search" in str(item.get("type") or "").lower()
        ]

    def answer(
        self, prompt_text: str, company: Company, project: Project, competitors: list[Competitor]
    ) -> ProviderAnswer:
        if not self.api_key:
            raise ValueError(f"Missing API key for provider {self.provider.name}")
        payload = {
            "model": self.provider.model_name or "doubao-seed-2-1-pro-260628",
            "input": prompt_text,
            "tools": [{"type": "web_search"}],
            "thinking": {"type": "disabled"},
            "store": False,
            "stream": False,
        }
        # One provider call per sample keeps repeated GEO measurements and spend auditable.
        max_attempts = max(1, min(int(self.provider.cost_rule.get("search_retry_attempts") or 1), 2))
        attempts: list[dict[str, Any]] = []
        transient_error: Exception | None = None
        # Volcengine is a domestic endpoint. Bypass machine-wide VPN variables because
        # long Responses API searches were observed to be disconnected by the proxy.
        with httpx.Client(
            timeout=_provider_http_timeout(self.timeout_seconds),
            transport=self.transport,
            trust_env=False,
        ) as client:
            for _attempt in range(max_attempts):
                try:
                    response = client.post(
                        f"{self.base_url}/responses",
                        headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                        json=payload,
                    )
                    _raise_provider_http_error(response, provider_label=self.provider_label)
                except httpx.TimeoutException as exc:
                    transient_error = exc
                    continue
                except ValueError as exc:
                    # Aggregate gateways occasionally fail upstream while a model is otherwise
                    # healthy. Retry that narrow transient class once; never hide billing,
                    # model-routing, or evidence-gate errors behind automatic retries.
                    if "upstream request failed" in str(exc).lower():
                        transient_error = exc
                        continue
                    raise
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("Volcengine Responses API returned an invalid payload")
                attempts.append(data)
                search_events = self._search_events(data)
                sources = _source_items_from_nested_payload(data)
                answer_text = self._answer_text(data)
                if search_events and sources and answer_text:
                    return ProviderAnswer(
                        prompt_text=prompt_text,
                        raw_answer=answer_text,
                        answer_summary=answer_text[:180],
                        source_items=sources,
                        raw_provider_payload={"attempts": attempts},
                        collection_method=self.collection_method,
                        search_verified=True,
                        search_event_count=len(search_events),
                        search_verification={
                            "gate": "Responses web_search event + source URLs + final answer",
                            "web_search_call_count": len(search_events),
                            "source_count": len(sources),
                            "accepted_attempt": len(attempts),
                            "original_prompt_preserved": True,
                        },
                    )
        if transient_error is not None:
            raise ValueError(
                f"{self.provider_label} 上游联网搜索连续失败 {max_attempts} 次：{str(transient_error)[:360]}"
            )
        raise ValueError(
            f"{self.provider_label} 本次未同时返回 Web Search 事件、来源 URL 和最终回答；"
            "为避免把未联网回答计入 GEO，结果已拒绝入库。"
        )


class XiaomaDomesticWebSearchProvider(VolcengineWebSearchProvider):
    """Xiaoma's OpenAI Responses-compatible domestic-model gateway.

    The gateway is only eligible for GEO evidence when it exposes an actual
    web_search_call plus structured source URLs.  A model name or a marketing
    label saying \"联网\" is deliberately not enough.
    """

    provider_label = "小马 API"
    collection_method = "aggregate_api_web_search"

    def __init__(
        self,
        provider: LLMProvider,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        super().__init__(provider, api_key=api_key, transport=transport)
        self.base_url = (
            provider.api_base_url or DEFAULT_BASE_URLS["xiaoma_domestic_web_search"]
        ).rstrip("/")


class QwenWebSearchProvider(BaseLLMSearchProvider):
    """DashScope native generation API with forced search and explicit sources."""

    def __init__(
        self,
        provider: LLMProvider,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.provider = provider
        self.api_key = api_key or (provider.auth_config or {}).get("api_key")
        configured = (provider.api_base_url or DEFAULT_BASE_URLS["qwen_compatible"]).rstrip("/")
        self.base_url = configured.replace("/compatible-mode/v1", "/api/v1")
        self.timeout_seconds = float(
            provider.cost_rule.get("timeout_seconds") or DEFAULT_CHAT_COMPLETION_TIMEOUT_SECONDS
        )
        self.transport = transport

    def answer(
        self, prompt_text: str, company: Company, project: Project, competitors: list[Competitor]
    ) -> ProviderAnswer:
        if not self.api_key:
            raise ValueError(f"Missing API key for provider {self.provider.name}")
        payload = {
            "model": self.provider.model_name or "qwen-plus",
            "input": {"messages": [{"role": "user", "content": prompt_text}]},
            "parameters": {
                "result_format": "message",
                "enable_search": True,
                "search_options": {
                    "forced_search": True,
                    "enable_source": True,
                    "enable_citation": True,
                    "citation_format": "[<number>]",
                    "search_strategy": str(self.provider.cost_rule.get("search_strategy") or "max"),
                },
            },
        }
        with httpx.Client(
            timeout=_provider_http_timeout(self.timeout_seconds),
            transport=self.transport,
        ) as client:
            response = client.post(
                f"{self.base_url}/services/aigc/text-generation/generation",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            _raise_provider_http_error(response, provider_label="阿里云百炼")
            data = response.json()
        output = data.get("output") if isinstance(data, dict) else None
        choices = output.get("choices") if isinstance(output, dict) else None
        if not choices or not isinstance(choices[0], dict):
            raise ValueError("Qwen response did not contain output.choices[0]")
        message = choices[0].get("message") or {}
        answer_text = str(message.get("content") or "").strip()
        search_info = output.get("search_info") if isinstance(output, dict) else None
        sources = _source_items_from_nested_payload(search_info or {})
        plugins = (data.get("usage") or {}).get("plugins") if isinstance(data, dict) else None
        search_count = int(((plugins or {}).get("search") or {}).get("count") or 0)
        if search_count < 1 or not search_info:
            raise ValueError("Qwen response did not prove that forced web search executed")
        if not sources:
            raise ValueError("Qwen web search returned no auditable source URLs")
        if not answer_text:
            raise ValueError("Qwen web search did not return a final answer")
        return ProviderAnswer(
            prompt_text=prompt_text,
            raw_answer=answer_text,
            answer_summary=answer_text[:180],
            source_items=sources,
            raw_provider_payload=data,
            collection_method="official_api_web_search",
            search_verified=True,
            search_event_count=search_count + 1,
            search_verification={
                "gate": "usage.plugins.search + search_info.search_results + final answer",
                "web_search_call_count": search_count,
                "source_count": len(sources),
                "forced_search": True,
            },
        )


class BailianQwenResponsesProvider(VolcengineWebSearchProvider):
    """Bailian's official Responses API with mandatory native Web Search evidence.

    Qwen's current Responses payload uses the same auditable primitives as Ark:
    ``web_search_call`` events, structured source URLs, and a final message.  Reusing
    the strict parser keeps all domestic-model evidence under one production rule.
    """

    provider_label = "阿里云百炼"
    collection_method = "official_api_web_search"

    def __init__(
        self,
        provider: LLMProvider,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        super().__init__(provider, api_key=api_key, transport=transport)
        self.base_url = (
            provider.api_base_url or DEFAULT_BASE_URLS["bailian_qwen_responses"]
        ).rstrip("/")

    def answer(
        self, prompt_text: str, company: Company, project: Project, competitors: list[Competitor]
    ) -> ProviderAnswer:
        answer = super().answer(prompt_text, company, project, competitors)
        answer.search_verification["provider"] = "bailian_responses"
        answer.search_verification["model"] = self.provider.model_name or "qwen3.7-plus"
        return answer


def get_provider_api_key(provider: LLMProvider) -> tuple[str | None, str]:
    settings = get_settings()
    provider_key = (provider.auth_config or {}).get("api_key")
    if provider_key:
        return str(provider_key), "provider.auth_config.api_key"
    encrypted_provider_key = (provider.auth_config or {}).get("api_key_encrypted")
    if encrypted_provider_key:
        try:
            return decrypt_secret(str(encrypted_provider_key)), "provider.auth_config.api_key_encrypted"
        except RuntimeError:
            return None, "provider.auth_config.api_key_encrypted"
    if provider.provider_type in {"qwen_compatible", "bailian_qwen_responses"}:
        if settings.qwen_api_key:
            return settings.qwen_api_key, "QWEN_API_KEY"
        if settings.dashscope_api_key:
            return settings.dashscope_api_key, "DASHSCOPE_API_KEY"
        return None, "QWEN_API_KEY 或 DASHSCOPE_API_KEY"
    env_name = ENV_KEY_BY_PROVIDER_TYPE.get(provider.provider_type)
    value = {
        "OPENAI_API_KEY": settings.openai_api_key,
        "DEEPSEEK_API_KEY": settings.deepseek_api_key,
        "KIMI_API_KEY": settings.kimi_api_key,
        "HUNYUAN_API_KEY": settings.hunyuan_api_key,
        "ARK_API_KEY": settings.ark_api_key,
        "QWEN_API_KEY": settings.qwen_api_key,
        "XIAOMA_API_KEY": getattr(settings, "xiaoma_api_key", None),
    }.get(env_name or "")
    if value:
        return value, env_name or "environment"
    return None, env_name or "not_required"


def get_provider_default_base_url(provider_type: str) -> str | None:
    return DEFAULT_BASE_URLS.get(provider_type)


def get_provider_onboarding() -> list[dict[str, Any]]:
    return PROVIDER_ONBOARDING


def diagnose_provider(provider: LLMProvider) -> dict[str, Any]:
    api_key, auth_source = get_provider_api_key(provider)
    base_url = (provider.api_base_url or get_provider_default_base_url(provider.provider_type) or "").rstrip("/")
    last_blocker = provider.cost_rule.get("last_blocker")
    last_probe_error = provider.cost_rule.get("last_probe_error")
    missing: list[str] = []
    warnings: list[str] = []
    recommendations: list[str] = []
    setup_steps: list[str] = []
    access_method = "chat_completion_api"
    search_mode = "llm_answer_without_live_web"
    search_access_status = "api_ready_no_live_search"
    if provider.status != "active":
        missing.append("status=active")
        recommendations.append("将渠道状态改为 active 前，请先解决 blocker 并完成一次测试调用。")
        setup_steps.append("确认模型 ID、API Key、Base URL 和账号权限后，将 Provider 状态改为 active。")
    if last_blocker:
        warnings.append(str(last_blocker))
        recommendations.append(f"先处理历史 blocker：{last_blocker}")
    if last_probe_error:
        warnings.append(f"最近恢复探针失败：{last_probe_error}")
        recommendations.append("如果该错误来自 DNS/网络，请在可出网环境重跑 Provider 探针；如果来自模型或鉴权，请先修正渠道配置。")
    if provider.provider_type not in {"mock", "browser_observation"} and not api_key:
        missing.append(auth_source)
        recommendations.append(f"配置 {auth_source}，或在 Provider auth_config 中写入 api_key。")
        setup_steps.append("先配置 Provider 级 API Key，或配置对应环境变量。")
    if provider.provider_type == "browser_observation":
        access_method = "browser_automation"
        search_mode = "web_ui_observation"
        search_access_status = "ready_for_observation" if base_url else "needs_config"
        recommendations.append("网页端观测适合低频抽样、截图留证和校验 API 结果差异，不建议作为每小时高频生产主链路。")
        recommendations.append("正式使用前应确认登录态、验证码、平台使用条款和免费额度限制。")
        setup_steps.append("配置网页入口 URL，并用浏览器自动化或人工辅助完成登录态验证。")
        setup_steps.append("先用 1-3 个目标问题做抽样观测，确认可读取答案和保存截图。")
        warnings.append("当前版本只登记浏览器观测渠道和运维口径，尚未内置网页自动化执行器。")
    elif provider.provider_type != "mock" and not base_url:
        missing.append("api_base_url")
        recommendations.append("配置 OpenAI-compatible API Base URL。")
        setup_steps.append("补充 API Base URL，通常填到 /v1。")
    if not provider.model_name:
        missing.append("model_name")
        setup_steps.append("填写模型名称。")
    if provider.provider_type == "openai_compatible":
        recommendations.append("OpenAI Compatible 渠道适合 API 中转站；Base URL 填到 /v1，例如 https://ccdan.cc.cd/v1。")
        recommendations.append(f"系统会调用 {base_url or 'Base URL'}/chat/completions，请确认中转站支持该接口和所填模型名。")
        setup_steps.append("用后台“测试调用”确认 /chat/completions 可用。")
    if provider.provider_type == "deepseek_web_search":
        access_method = "official_api_with_web_search"
        search_mode = "provider_web_search"
        search_access_status = "ready_for_collection"
        recommendations.append("使用 DeepSeek 官方 Anthropic 兼容接口的 Web Search；没有搜索结果工件时测试会失败。")
        recommendations.append("该结果应标记为“DeepSeek API + Search”，不能标记成网页端原样回答。")
        setup_steps.append("先用一个非品牌采购问题验证 web_search_tool_result 和最终回答同时返回。")
    if provider.provider_type == "kimi_web_search":
        access_method = "official_api_with_web_search"
        search_mode = "formula_web_search"
        search_access_status = "ready_for_collection"
        recommendations.append("Kimi 联网搜索使用 moonshot/web-search:latest 官方工具；必须执行 fiber 并返回来源 URL。")
        setup_steps.append("后台测试应同时返回工具执行、来源 URL 和最终回答，再用于项目采集。")
    if provider.provider_type == "hunyuan_web_search":
        access_method = "official_api_with_web_search"
        search_mode = "hunyuan_forced_search_enhancement"
        search_access_status = "ready_for_collection"
        recommendations.append("系统强制开启混元搜索增强、search_info 与引用；缺少来源 URL 时拒绝入库。")
        setup_steps.append("使用非品牌采购问题验证 search_info、来源 URL 和最终回答同时返回。")
    if provider.provider_type == "qwen_compatible":
        access_method = "official_api_with_web_search"
        search_mode = "dashscope_forced_web_search"
        search_access_status = "ready_for_collection"
        setup_steps.append("使用一个非品牌采购问题，验证 search_info、usage.plugins.search 和最终回答同时返回。")
        recommendations.append("系统通过 DashScope 原生接口固定 forced_search=true，并保存显式来源列表。")
    if provider.provider_type == "bailian_qwen_responses":
        access_method = "official_api_with_web_search"
        search_mode = "qwen_responses_web_search"
        search_access_status = "ready_for_collection"
        setup_steps.append("使用非品牌采购问题验证 web_search_call、来源 URL 和最终回答同时返回。")
        recommendations.append("系统使用百炼官方 Responses API 固定 web_search；没有搜索事件、来源或最终回答时拒绝入库。")
    if provider.provider_type == "xiaoma_domestic_web_search":
        access_method = "aggregate_api_with_web_search"
        search_mode = "responses_web_search"
        search_access_status = "ready_for_collection"
        setup_steps.append("先读取 GET /v1/models，只使用该 Key 已授权的国内文本模型。")
        setup_steps.append("后台测试必须同时返回 web_search_call、结构化来源 URL 和最终回答。")
        recommendations.append("小马是聚合 API；页面会明确展示聚合来源，不会标记为模型官方直连。")
        recommendations.append("切换千问、Kimi、DeepSeek、豆包或 GLM 时，应分别创建渠道并分别通过联网测试。")
    if provider.provider_type == "volcengine_ark" and not provider.api_base_url:
        warnings.append("未显式配置 Base URL，将使用火山方舟北京区官方 Responses API 地址。")
    if provider.provider_type == "volcengine_ark":
        access_method = "official_api_with_web_search"
        search_mode = "ark_responses_web_search"
        search_access_status = "ready_for_collection"
        recommendations.append("系统使用火山方舟 Responses API 的内置 Web Search；缺少搜索事件或来源 URL 时拒绝入库。")
        recommendations.append("默认模型为低成本 Doubao Seed 2.0 Lite；是否仍有免费额度需以火山方舟控制台为准。")
        setup_steps.append("用非品牌采购问题验证 web_search 事件、来源 URL 和最终回答同时返回。")
    if provider.provider_type == "mock":
        access_method = "mock"
        search_mode = "mock_simulation"
        search_access_status = "ready_for_demo"
        recommendations.append("Mock 渠道可用于开发闭环，不代表真实大模型搜索结果。")
        setup_steps.append("用于演示闭环；上线前至少配置一个真实 Provider。")
    if provider.provider_type != "mock" and missing:
        search_access_status = "needs_config"
    return {
        "provider_id": provider.id,
        "provider_type": provider.provider_type,
        "ready": len(missing) == 0,
        "auth_ready": provider.provider_type == "mock" or bool(api_key),
        "auth_source": auth_source if provider.provider_type != "mock" else "not_required",
        "base_url": base_url or None,
        "endpoint_path": (
            "/v1/messages" if provider.provider_type == "deepseek_web_search"
            else "/formulas/moonshot/web-search:latest" if provider.provider_type == "kimi_web_search"
            else "/chat/completions" if provider.provider_type == "hunyuan_web_search"
            else "/services/aigc/text-generation/generation" if provider.provider_type == "qwen_compatible"
            else "/responses" if provider.provider_type == "bailian_qwen_responses"
            else "/responses" if provider.provider_type == "volcengine_ark"
            else "/responses" if provider.provider_type == "xiaoma_domestic_web_search"
            else "/chat/completions"
        ),
        "supports_web_search": provider.provider_type in {
            "deepseek_web_search", "kimi_web_search", "hunyuan_web_search", "qwen_compatible", "bailian_qwen_responses", "volcengine_ark", "xiaoma_domestic_web_search"
        },
        "access_method": access_method,
        "search_mode": search_mode,
        "search_access_status": search_access_status,
        "setup_steps": setup_steps,
        "last_blocker": str(last_blocker) if last_blocker else None,
        "missing": missing,
        "warnings": warnings,
        "recommendations": recommendations,
    }


def get_search_provider(provider: LLMProvider) -> BaseLLMSearchProvider:
    api_key, _auth_source = get_provider_api_key(provider)
    if provider.provider_type in {"openai", "openai_compatible"}:
        return OpenAICompatibleSearchProvider(
            provider,
            api_key=api_key,
            default_base_url=DEFAULT_BASE_URLS["openai_compatible"],
        )
    if provider.provider_type == "deepseek_web_search":
        return DeepSeekWebSearchProvider(provider, api_key=api_key)
    if provider.provider_type == "kimi_web_search":
        return KimiWebSearchProvider(provider, api_key=api_key)
    if provider.provider_type == "hunyuan_web_search":
        return HunyuanWebSearchProvider(provider, api_key=api_key)
    if provider.provider_type == "volcengine_ark":
        return VolcengineWebSearchProvider(provider, api_key=api_key)
    if provider.provider_type == "xiaoma_domestic_web_search":
        return XiaomaDomesticWebSearchProvider(provider, api_key=api_key)
    if provider.provider_type == "qwen_compatible":
        return QwenWebSearchProvider(provider, api_key=api_key)
    if provider.provider_type == "bailian_qwen_responses":
        return BailianQwenResponsesProvider(provider, api_key=api_key)
    if provider.provider_type == "mock":
        return MockLLMSearchProvider(provider)
    raise ValueError(
        f"未注册的模型渠道类型：{provider.provider_type}。请先选择已支持的官方联网适配器，系统不会回退到 Mock。"
    )
