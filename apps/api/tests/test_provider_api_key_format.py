from app.models import LLMProvider
from app.services.llm_provider import diagnose_provider, provider_api_key_format_error


def test_provider_api_key_accepts_ascii_console_value() -> None:
    assert provider_api_key_format_error("sk-valid_123-ABC") is None


def test_provider_api_key_rejects_pasted_label_and_fullwidth_punctuation() -> None:
    message = provider_api_key_format_error("DeepSeek API Key：sk-secret")

    assert message is not None
    assert "中文或全角字符" in message
    assert "sk-secret" not in message


def test_provider_api_key_rejects_whitespace_and_mask_placeholder() -> None:
    assert "空格" in (provider_api_key_format_error("sk-secret\n") or "")
    assert "脱敏占位符" in (provider_api_key_format_error("***configured***") or "")


def test_diagnostic_does_not_mark_malformed_key_ready() -> None:
    provider = LLMProvider(
        id=4,
        name="DeepSeek",
        provider_type="deepseek_web_search",
        api_base_url="https://api.deepseek.com/anthropic",
        model_name="deepseek-v4-flash",
        auth_config={"api_key": "DeepSeek API Key：sk-secret"},
        cost_rule={},
        status="active",
    )

    diagnostic = diagnose_provider(provider)

    assert diagnostic["auth_ready"] is False
    assert "api_key_format" in diagnostic["missing"]
    assert diagnostic["warnings"] == ["API Key 包含中文或全角字符"]
