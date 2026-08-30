import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import LLMProvider
from app.services.workspace_secrets import normalize_provider_auth_config


ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"

DEFAULT_PROVIDERS = [
    ("方舟 GLM-5.2 GEO 采集", "glm-5-2-260617", "active"),
    ("方舟 Doubao Seed 2.1 Pro GEO 采集", "doubao-seed-2-1-pro-260628", "active"),
    ("方舟 Kimi-K2 GEO 采集", "kimi-k2-250905", "inactive"),
    ("方舟 DeepSeek-V3.2 GEO 采集", "deepseek-v3-2-251201", "active"),
]


def upsert_ark_providers(api_key: str | None, kimi_model: str | None = None, activate_kimi: bool = False) -> list[dict]:
    provider_specs = list(DEFAULT_PROVIDERS)
    if kimi_model or activate_kimi:
        provider_specs[2] = (
            "方舟 Kimi-K2 GEO 采集",
            kimi_model or provider_specs[2][1],
            "active" if activate_kimi else "inactive",
        )

    touched: list[dict] = []
    with SessionLocal() as db:
        for name, model_name, status in provider_specs:
            provider = db.scalar(select(LLMProvider).where(LLMProvider.name == name))
            if provider is None:
                provider = LLMProvider(
                    name=name,
                    provider_type="volcengine_ark",
                    api_base_url=ARK_BASE_URL,
                    model_name=model_name,
                    auth_config={},
                    cost_rule={},
                    status=status,
                )
                db.add(provider)
                db.flush()

            provider.provider_type = "volcengine_ark"
            provider.api_base_url = ARK_BASE_URL
            provider.model_name = model_name
            provider.status = status
            provider.auth_config = normalize_provider_auth_config(
                {"api_key": api_key} if api_key else {},
                existing=provider.auth_config,
            )
            touched.append(
                {
                    "id": provider.id,
                    "name": provider.name,
                    "model_name": provider.model_name,
                    "status": provider.status,
                    "api_key_configured": bool(provider.auth_config.get("api_key_encrypted")),
                }
            )
        db.commit()
    return touched


def main() -> None:
    parser = argparse.ArgumentParser(description="Upsert Volcengine Ark providers for GEO collection.")
    parser.add_argument("--kimi-model", help="Ark endpoint/model id for Kimi-K2. Leave unset until verified.")
    parser.add_argument("--activate-kimi", action="store_true", help="Mark the Kimi provider active after setting its model id.")
    args = parser.parse_args()

    api_key = os.getenv("ARK_API_KEY")
    if not api_key:
        raise SystemExit("Missing ARK_API_KEY. Export it in the shell before running this script.")

    for item in upsert_ark_providers(api_key=api_key, kimi_model=args.kimi_model, activate_kimi=args.activate_kimi):
        print(item)


if __name__ == "__main__":
    main()
