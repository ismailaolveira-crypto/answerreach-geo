import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.models import Company, LLMProvider, LLMProviderTestRun, Project
from app.services.alert import create_provider_failure_alert
from app.services.llm_provider import diagnose_provider, get_search_provider
from app.services.usage import record_usage


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_real_provider_probe.json"


def _parse_ids(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _default_prompt(project: Project) -> str:
    return (
        "企业在采购大模型 API 治理、Token 统一管控、AI 调用审计服务时，"
        "应该重点比较哪些能力和案例？"
    )


def probe_providers(
    *,
    project_id: int,
    provider_ids: list[int],
    prompt_text: str | None,
    output_path: Path,
    allow_inactive: bool = False,
    activate_on_success: bool = False,
) -> dict[str, Any]:
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        if project is None:
            raise ValueError(f"Project {project_id} not found")
        company = db.get(Company, project.company_id)
        if company is None:
            raise ValueError(f"Company for project {project_id} not found")
        prompt = prompt_text or _default_prompt(project)
        providers = list(
            db.scalars(
                select(LLMProvider)
                .where(LLMProvider.id.in_(provider_ids))
                .order_by(LLMProvider.id.asc())
            )
        )
        provider_map = {provider.id: provider for provider in providers}
        results: list[dict[str, Any]] = []
        for provider_id in provider_ids:
            provider = provider_map.get(provider_id)
            if provider is None:
                results.append({"provider_id": provider_id, "ok": False, "error": "Provider not found"})
                continue
            diagnostic = diagnose_provider(provider)
            started = perf_counter()
            try:
                status_blocked = provider.status != "active"
                if status_blocked and not allow_inactive:
                    raise ValueError("Provider is not active; activate it only after model id/key/base url are confirmed.")
                effective_missing = [
                    str(item)
                    for item in diagnostic["missing"]
                    if not (allow_inactive and str(item) == "status=active")
                ]
                if effective_missing:
                    missing = "、".join(effective_missing) or "必要配置"
                    raise ValueError(f"Provider not ready: {missing}")
                answer = get_search_provider(provider).answer(prompt, company, project, [])
                latency_ms = int((perf_counter() - started) * 1000)
                if provider.cost_rule.get("last_blocker"):
                    provider.cost_rule = {
                        key: value
                        for key, value in provider.cost_rule.items()
                        if key not in {"last_blocker", "last_probe_error"}
                    }
                if activate_on_success and status_blocked:
                    provider.status = "active"
                test_run = LLMProviderTestRun(
                    provider_id=provider.id,
                    ok=True,
                    prompt_text=answer.prompt_text,
                    company_name=company.name,
                    industry=project.target_industry or company.industry,
                    answer_summary=answer.answer_summary,
                    raw_answer_preview=answer.raw_answer[:1000],
                    latency_ms=latency_ms,
                )
                db.add(test_run)
                db.flush()
                record_usage(
                    db,
                    provider=provider,
                    action="provider.probe",
                    prompt_text=prompt,
                    completion_text=answer.raw_answer,
                    company_id=company.id,
                    project_id=project.id,
                    provider_test_run_id=test_run.id,
                    detail={"ok": True, "source": "probe_real_providers.py"},
                )
                results.append(
                    {
                        "provider_id": provider.id,
                        "name": provider.name,
                        "provider_type": provider.provider_type,
                        "model_name": provider.model_name,
                        "ok": True,
                        "test_run_id": test_run.id,
                        "latency_ms": latency_ms,
                        "answer_summary": answer.answer_summary[:180],
                        "search_mode": diagnostic["search_mode"],
                        "activated": bool(activate_on_success and status_blocked),
                        "status_before_probe": "inactive" if status_blocked else provider.status,
                    }
                )
            except Exception as exc:
                latency_ms = int((perf_counter() - started) * 1000)
                provider.cost_rule = {**(provider.cost_rule or {}), "last_probe_error": str(exc)[:500]}
                test_run = LLMProviderTestRun(
                    provider_id=provider.id,
                    ok=False,
                    prompt_text=prompt,
                    company_name=company.name,
                    industry=project.target_industry or company.industry,
                    error_message=str(exc),
                    latency_ms=latency_ms,
                )
                db.add(test_run)
                db.flush()
                alert = create_provider_failure_alert(
                    db,
                    provider=provider,
                    provider_test_run_id=test_run.id,
                    prompt_text=prompt,
                    error_message=str(exc),
                )
                record_usage(
                    db,
                    provider=provider,
                    action="provider.probe",
                    prompt_text=prompt,
                    completion_text="",
                    company_id=company.id,
                    project_id=project.id,
                    provider_test_run_id=test_run.id,
                    detail={"ok": False, "error": str(exc), "source": "probe_real_providers.py"},
                )
                results.append(
                    {
                        "provider_id": provider.id,
                        "name": provider.name,
                        "provider_type": provider.provider_type,
                        "model_name": provider.model_name,
                        "ok": False,
                        "test_run_id": test_run.id,
                        "alert_id": alert.id,
                        "latency_ms": latency_ms,
                        "error": str(exc),
                        "search_mode": diagnostic["search_mode"],
                        "missing": [
                            str(item)
                            for item in diagnostic["missing"]
                            if not (allow_inactive and str(item) == "status=active")
                        ],
                        "last_blocker": diagnostic.get("last_blocker"),
                    }
                )
        db.commit()
    payload = {
        "ok": all(item.get("ok") for item in results) if results else False,
        "project_id": project_id,
        "provider_ids": provider_ids,
        "prompt_text": prompt_text,
        "allow_inactive": allow_inactive,
        "activate_on_success": activate_on_success,
        "results": results,
        "created_at": datetime.now(UTC).isoformat(),
        "safety": {"raw_answers_printed": False, "api_keys_printed": False},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe real LLM providers and record provider test runs.")
    parser.add_argument("--project-id", type=int, default=1)
    parser.add_argument("--provider-ids", required=True)
    parser.add_argument("--prompt", default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--allow-inactive",
        action="store_true",
        help="Probe inactive providers without changing their status. Other missing config still blocks.",
    )
    parser.add_argument(
        "--activate-on-success",
        action="store_true",
        help="Mark an inactive provider active only after a successful probe.",
    )
    args = parser.parse_args()
    result = probe_providers(
        project_id=args.project_id,
        provider_ids=_parse_ids(args.provider_ids),
        prompt_text=args.prompt,
        output_path=args.output,
        allow_inactive=args.allow_inactive,
        activate_on_success=args.activate_on_success,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
