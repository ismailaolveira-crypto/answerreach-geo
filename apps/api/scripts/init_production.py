import argparse
import json
import os
import secrets
import string
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.models import LLMProvider, User
from app.services.auth import hash_password
from app.services.report_templates import seed_default_report_template
from app.services.review_rules import seed_default_review_rules


ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_ARK_PROVIDERS = [
    ("方舟 GLM-5.2 GEO 采集", "glm-5-2-260617", "active"),
    ("方舟 Doubao Seed 2.1 Pro GEO 采集", "doubao-seed-2-1-pro-260628", "active"),
    ("方舟 Kimi-K2 GEO 采集", "kimi-k2-250905", "inactive"),
    ("方舟 DeepSeek-V3.2 GEO 采集", "deepseek-v3-2-251201", "active"),
]


def _random_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def init_production(admin_email: str, admin_password: str | None) -> dict:
    ark_api_key = os.getenv("ARK_API_KEY")
    created_password = admin_password or _random_password()

    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.email == admin_email))
        created_admin = False
        if admin is None:
            admin = User(
                company_id=None,
                name="系统管理员",
                email=admin_email,
                password_hash=hash_password(created_password),
                role="super_admin",
                status="active",
            )
            db.add(admin)
            db.flush()
            created_admin = True
        else:
            admin.role = "super_admin"
            admin.status = "active"
            if admin_password:
                admin.password_hash = hash_password(admin_password)

        review_rules = seed_default_review_rules(db)
        report_template = seed_default_report_template(db)
        report_template_id = report_template.id

        providers = []
        for name, model_name, status in DEFAULT_ARK_PROVIDERS:
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
            auth_config = dict(provider.auth_config or {})
            if ark_api_key:
                auth_config["api_key"] = ark_api_key
            provider.auth_config = auth_config
            providers.append(
                {
                    "id": provider.id,
                    "name": provider.name,
                    "model_name": provider.model_name,
                    "status": provider.status,
                    "api_key_configured": bool(provider.auth_config.get("api_key")),
                }
            )

        db.commit()

    return {
        "admin_email": admin_email,
        "admin_created": created_admin,
        "admin_password": created_password if created_admin and not admin_password else None,
        "review_rule_count": len(review_rules),
        "report_template_id": report_template_id,
        "providers": providers,
        "ark_api_key_configured": bool(ark_api_key),
        "warning": "Store the generated admin_password immediately; it is printed only once."
        if created_admin and not admin_password
        else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize production database for GEO platform.")
    parser.add_argument("--admin-email", default=os.getenv("ADMIN_EMAIL", "admin@example.com"))
    parser.add_argument("--admin-password", default=os.getenv("ADMIN_PASSWORD"))
    args = parser.parse_args()
    print(json.dumps(init_production(args.admin_email, args.admin_password), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
