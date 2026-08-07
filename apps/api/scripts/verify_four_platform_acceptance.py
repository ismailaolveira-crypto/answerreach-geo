"""Audit real product readiness for the four V1 GEO platforms.

This verifier never calls a model and never prints credentials.  It checks the
current product database for the exact official provider, its newest connection
test, and at least one auditable observation produced by that same provider.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from urllib.parse import unquote, urlparse

from sqlalchemy import select


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models import GeoEvidence, LLMProvider, LLMProviderTestRun  # noqa: E402
from app.services.llm_provider import diagnose_provider  # noqa: E402


PLATFORMS = (
    ("deepseek", "DeepSeek", "deepseek_web_search", ""),
    ("qianwen", "通义千问", "bailian_qwen_responses", ""),
    ("doubao", "豆包", "volcengine_ark", "doubao"),
    ("glm", "智谱 GLM", "volcengine_ark", "glm"),
)


def artifact_is_complete(uri: str | None, provider_id: int) -> bool:
    if not uri:
        return False
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return False
    path = Path(unquote(parsed.path))
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    verification = payload.get("search_verification") or {}
    return bool(
        payload.get("schema_version") == "spring-yuan-provider-web-search/v1"
        and int(payload.get("provider_id") or 0) == provider_id
        and str(payload.get("answer") or "").strip()
        and payload.get("sources")
        and int(verification.get("web_search_call_count") or 0) >= 1
        and int(verification.get("source_count") or 0) >= 1
        and verification.get("original_prompt_preserved") is True
        and payload.get("raw_provider_response")
    )


def select_provider(providers: list[LLMProvider], provider_type: str, model_hint: str) -> LLMProvider | None:
    matches = [item for item in providers if item.provider_type == provider_type and item.status == "active"]
    if model_hint:
        matches = [item for item in matches if model_hint in f"{item.name} {item.model_name}".lower()]
    return max(matches, key=lambda item: item.id, default=None)


def main() -> int:
    with SessionLocal() as db:
        providers = list(db.scalars(select(LLMProvider)))
        evidence_rows = list(
            db.scalars(
                select(GeoEvidence)
                .where(GeoEvidence.collection_method == "official_api_web_search")
                .order_by(GeoEvidence.captured_at.desc(), GeoEvidence.id.desc())
            )
        )
        results: list[dict] = []
        for model_key, label, provider_type, model_hint in PLATFORMS:
            provider = select_provider(providers, provider_type, model_hint)
            diagnostic = diagnose_provider(provider) if provider else None
            latest_test = None
            evidence = None
            if provider:
                latest_test = db.scalar(
                    select(LLMProviderTestRun)
                    .where(LLMProviderTestRun.provider_id == provider.id)
                    .order_by(LLMProviderTestRun.created_at.desc(), LLMProviderTestRun.id.desc())
                )
                evidence = next(
                    (
                        item for item in evidence_rows
                        if item.model_key == model_key
                        and int((item.sampling_environment or {}).get("provider_id") or 0) == provider.id
                    ),
                    None,
                )
            evidence_ok = bool(
                evidence
                and evidence.is_real_provider_evidence
                and evidence.source_items
                and (evidence.sampling_environment or {}).get("search_verified") is True
                and int((evidence.sampling_environment or {}).get("search_event_count") or 0) >= 1
                and artifact_is_complete(evidence.raw_artifact_uri, provider.id)
            )
            checks = {
                "official_provider_active": bool(provider),
                "api_key_configured": bool(diagnostic and diagnostic.get("auth_ready")),
                "latest_connection_test_passed": bool(latest_test and latest_test.ok),
                "auditable_observation_archived": evidence_ok,
            }
            blockers: list[str] = []
            if not provider:
                blockers.append("未配置官方 Provider")
            elif not checks["api_key_configured"]:
                blockers.append("API Key 未配置")
            elif latest_test and not latest_test.ok:
                blockers.append((latest_test.error_message or "最新连接测试失败")[:300])
            elif not latest_test:
                blockers.append("尚未执行真实连接测试")
            if provider and not evidence_ok:
                blockers.append("尚无该官方 Provider 生成的完整联网证据")
            results.append({
                "key": model_key,
                "label": label,
                "provider_id": provider.id if provider else None,
                "model": provider.model_name if provider else None,
                "latest_test_id": latest_test.id if latest_test else None,
                "evidence_id": evidence.id if evidence else None,
                "checks": checks,
                "accepted": all(checks.values()),
                "blockers": blockers,
            })

    payload = {
        "schema": "spring-yuan-four-platform-acceptance/v1",
        "accepted": all(item["accepted"] for item in results),
        "passed": sum(1 for item in results if item["accepted"]),
        "total": len(results),
        "platforms": results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
