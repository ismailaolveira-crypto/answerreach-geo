import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.models import LLMProvider


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_browser_observation_providers.json"

PROVIDERS = [
    {
        "name": "豆包网页端观测",
        "api_base_url": "https://www.doubao.com/chat/",
        "model_name": "doubao-web-observation",
        "platform_name": "豆包",
    },
    {
        "name": "DeepSeek 网页端观测",
        "api_base_url": "https://chat.deepseek.com/",
        "model_name": "deepseek-web-observation",
        "platform_name": "DeepSeek",
    },
    {
        "name": "Kimi 网页端观测",
        "api_base_url": "https://www.kimi.com/",
        "model_name": "kimi-web-observation",
        "platform_name": "Kimi",
    },
    {
        "name": "千问网页端观测",
        "api_base_url": "https://www.qianwen.com/",
        "model_name": "qwen-web-observation",
        "platform_name": "千问",
    },
]


def ensure_browser_observation_providers(*, output_path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    with SessionLocal() as db:
        for template in PROVIDERS:
            provider = db.scalar(
                select(LLMProvider).where(
                    LLMProvider.provider_type == "browser_observation",
                    LLMProvider.name == template["name"],
                )
            )
            action = "updated"
            if provider is None:
                provider = LLMProvider(
                    name=template["name"],
                    provider_type="browser_observation",
                    api_base_url=template["api_base_url"],
                    model_name=template["model_name"],
                    auth_config={},
                    cost_rule={"platform_name": template["platform_name"], "evidence_mode": "manual_browser"},
                    status="active",
                )
                db.add(provider)
                db.flush()
                action = "created"
            else:
                provider.api_base_url = template["api_base_url"]
                provider.model_name = template["model_name"]
                provider.cost_rule = {
                    **(provider.cost_rule or {}),
                    "platform_name": template["platform_name"],
                    "evidence_mode": "manual_browser",
                }
                provider.status = "active"
            results.append(
                {
                    "id": provider.id,
                    "name": provider.name,
                    "platform_name": template["platform_name"],
                    "api_base_url": provider.api_base_url,
                    "action": action,
                }
            )
        db.commit()
    payload = {
        "ok": True,
        "provider_count": len(results),
        "providers": results,
        "created_at": datetime.now(UTC).isoformat(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    result = ensure_browser_observation_providers()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
