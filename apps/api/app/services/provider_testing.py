from time import perf_counter

from sqlalchemy.orm import Session

from app.models import (
    Company,
    LLMProvider,
    LLMProviderTestRun,
    Project,
    SystemAlert,
    User,
)
from app.schemas.search import LLMProviderTestRequest, LLMProviderTestResult
from app.services.audit import record_audit_log
from app.services.llm_provider import get_search_provider
from app.services.usage import enforce_monthly_search_budget, record_usage


def _create_failure_alert(
    db: Session,
    *,
    provider: LLMProvider,
    provider_test_run_id: int,
    prompt_text: str,
    error_message: str,
) -> SystemAlert:
    alert = SystemAlert(
        provider_id=provider.id,
        provider_test_run_id=provider_test_run_id,
        alert_type="provider.test_failed",
        severity="critical",
        status="open",
        title=f"模型渠道测试失败：{provider.name}",
        message=error_message[:1000],
        detail_json={
            "provider_type": provider.provider_type,
            "model_name": provider.model_name,
            "prompt_text": prompt_text,
        },
    )
    db.add(alert)
    db.flush()
    return alert


def run_provider_test(
    db: Session,
    *,
    provider: LLMProvider,
    payload: LLMProviderTestRequest,
    user: User,
) -> LLMProviderTestResult:
    """Run and persist one Provider connectivity test for HTTP and Worker callers."""

    company = Company(
        name=payload.company_name,
        industry=payload.industry,
        website_url="https://example.com",
        brand_aliases=[],
    )
    project = Project(
        company_id=0,
        name="Provider smoke test",
        target_industry=payload.industry,
        target_audience="企业采购决策者",
    )
    started_at = perf_counter()
    try:
        enforce_monthly_search_budget(db, provider)
        search_provider = get_search_provider(provider)
        if hasattr(search_provider, "timeout_seconds"):
            search_provider.timeout_seconds = max(
                30.0,
                min(float(search_provider.timeout_seconds), 180.0),
            )
        answer = search_provider.answer(payload.prompt_text, company, project, [])
        latency_ms = int((perf_counter() - started_at) * 1000)
        test_run = LLMProviderTestRun(
            provider_id=provider.id,
            actor_user_id=user.id,
            ok=True,
            prompt_text=answer.prompt_text,
            company_name=payload.company_name,
            industry=payload.industry,
            answer_summary=answer.answer_summary,
            raw_answer_preview=answer.raw_answer[:1000],
            latency_ms=latency_ms,
        )
        db.add(test_run)
        db.flush()
        record_usage(
            db,
            provider=provider,
            action="provider.test",
            prompt_text=payload.prompt_text,
            completion_text=answer.raw_answer,
            provider_test_run_id=test_run.id,
            detail={"ok": True},
        )
        record_audit_log(
            db,
            user=user,
            action="provider.test",
            resource_type="llm_provider",
            resource_id=provider.id,
            detail={"ok": True, "prompt_text": payload.prompt_text, "test_run_id": test_run.id},
        )
        db.commit()
        db.refresh(test_run)
        return LLMProviderTestResult.model_validate(test_run)
    except Exception as exc:
        latency_ms = int((perf_counter() - started_at) * 1000)
        test_run = LLMProviderTestRun(
            provider_id=provider.id,
            actor_user_id=user.id,
            ok=False,
            prompt_text=payload.prompt_text,
            company_name=payload.company_name,
            industry=payload.industry,
            error_message=str(exc),
            latency_ms=latency_ms,
        )
        db.add(test_run)
        db.flush()
        record_usage(
            db,
            provider=provider,
            action="provider.test",
            prompt_text=payload.prompt_text,
            completion_text="",
            provider_test_run_id=test_run.id,
            detail={"ok": False, "error": str(exc)},
        )
        alert = _create_failure_alert(
            db,
            provider=provider,
            provider_test_run_id=test_run.id,
            prompt_text=payload.prompt_text,
            error_message=str(exc),
        )
        record_audit_log(
            db,
            user=user,
            action="provider.test",
            resource_type="llm_provider",
            resource_id=provider.id,
            detail={
                "ok": False,
                "prompt_text": payload.prompt_text,
                "error": str(exc),
                "test_run_id": test_run.id,
                "alert_id": alert.id,
            },
        )
        db.commit()
        db.refresh(test_run)
        return LLMProviderTestResult.model_validate(test_run)
