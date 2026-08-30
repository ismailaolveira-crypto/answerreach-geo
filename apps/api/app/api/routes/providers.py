import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import Company, CrawlResult, CrawlTask, LLMProvider, LLMProviderTestRun, Project, QueueJob, UsageRecord, User
from app.schemas.common import APIMessage
from app.schemas.search import (
    LLMProviderCreate,
    LLMProviderCollectionSummary,
    LLMProviderDiagnostic,
    LLMProviderOnboardingItem,
    LLMProviderReadiness,
    LLMProviderRead,
    LLMProviderTestRequest,
    LLMProviderTestResult,
    LLMProviderUpdate,
    QueueJobRead,
)
from app.services.audit import record_audit_log
from app.services.alert import create_provider_failure_alert
from app.services.llm_provider import diagnose_provider, get_provider_onboarding, get_search_provider
from app.services.usage import enforce_monthly_search_budget, record_usage
from app.services.workspace_secrets import normalize_provider_auth_config

router = APIRouter(prefix="/llm-providers", tags=["llm-providers"])


def _project_output_root() -> Path:
    """Resolve the shared output directory in both source and container layouts."""
    api_root = Path(__file__).resolve().parents[3]
    if api_root.name == "api" and api_root.parent.name == "apps":
        return api_root.parents[1] / "outputs"
    return api_root / "outputs"


LATEST_NETWORK_CHECK_OUTPUT = _project_output_root() / "latest_provider_network_check.json"


def get_provider_or_404(db: Session, provider_id: int) -> LLMProvider:
    provider = db.get(LLMProvider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="LLM provider not found")
    return provider


@router.get("", response_model=list[LLMProviderRead])
def list_providers(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[LLMProvider]:
    return list(db.scalars(select(LLMProvider).order_by(LLMProvider.created_at.desc())))


@router.get("/onboarding", response_model=list[LLMProviderOnboardingItem])
def list_provider_onboarding(
    _user: User = Depends(require_roles("super_admin")),
) -> list[dict]:
    return get_provider_onboarding()


@router.get("/network-check/latest")
def get_latest_provider_network_check(
    _user: User = Depends(require_roles("super_admin")),
) -> dict:
    if not LATEST_NETWORK_CHECK_OUTPUT.exists():
        return {
            "available": False,
            "ok": None,
            "output": str(LATEST_NETWORK_CHECK_OUTPUT),
            "results": [],
            "message": "No provider network preflight has been recorded yet.",
        }
    try:
        payload = json.loads(LATEST_NETWORK_CHECK_OUTPUT.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid provider network check output: {exc}") from exc
    payload["available"] = True
    payload["output"] = str(LATEST_NETWORK_CHECK_OUTPUT)
    return payload


@router.get("/readiness", response_model=list[LLMProviderReadiness])
def list_provider_readiness(
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles("super_admin")),
) -> list[dict]:
    """Return cached configuration and test state without calling a model."""
    providers = list(db.scalars(select(LLMProvider).order_by(LLMProvider.created_at.desc())))
    test_runs = list(
        db.scalars(
            select(LLMProviderTestRun).order_by(
                LLMProviderTestRun.created_at.desc(),
                LLMProviderTestRun.id.desc(),
            )
        )
    )
    latest_by_provider: dict[int, LLMProviderTestRun] = {}
    for run in test_runs:
        latest_by_provider.setdefault(run.provider_id, run)

    rows: list[dict] = []
    for provider in providers:
        diagnostic = diagnose_provider(provider)
        latest_test = latest_by_provider.get(provider.id)
        test_fresh = bool(
            latest_test is not None
            and (
                provider.updated_at is None
                or latest_test.created_at >= provider.updated_at
            )
        )
        collection_ready = bool(
            diagnostic["ready"]
            and diagnostic["supports_web_search"]
            and latest_test is not None
            and latest_test.ok
            and test_fresh
        )
        if collection_ready:
            blocker = None
        elif "api_key_format" in diagnostic["missing"]:
            format_warning = next(
                (
                    warning
                    for warning in diagnostic["warnings"]
                    if str(warning).startswith("API Key ")
                ),
                "API Key 格式错误",
            )
            blocker = f"{format_warning}。请重新粘贴控制台生成的 Key 原文"
        elif not diagnostic["auth_ready"]:
            blocker = "API Key 尚未配置"
        elif latest_test is None:
            blocker = "尚未主动测试渠道"
        elif not test_fresh:
            blocker = "配置已变更，请重新测试渠道"
        elif not latest_test.ok:
            blocker = latest_test.error_message or "最近一次渠道测试未通过"
        elif not diagnostic["supports_web_search"]:
            blocker = "尚未证明具备联网搜索能力"
        else:
            blocker = diagnostic.get("last_blocker") or "渠道尚未达到采集门禁"
        rows.append(
            {
                "provider_id": provider.id,
                "diagnostic": diagnostic,
                "latest_test": latest_test,
                "test_fresh": test_fresh,
                "collection_ready": collection_ready,
                "collection_blocker": blocker,
            }
        )
    return rows


@router.get("/{provider_id}", response_model=LLMProviderRead)
def get_provider(
    provider_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> LLMProvider:
    return get_provider_or_404(db, provider_id)


@router.get("/{provider_id}/diagnostic", response_model=LLMProviderDiagnostic)
def get_provider_diagnostic(
    provider_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles("super_admin")),
) -> dict:
    provider = get_provider_or_404(db, provider_id)
    return diagnose_provider(provider)


@router.get("/{provider_id}/collection-summary", response_model=LLMProviderCollectionSummary)
def get_provider_collection_summary(
    provider_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles("super_admin")),
) -> LLMProviderCollectionSummary:
    provider = get_provider_or_404(db, provider_id)
    diagnostic = diagnose_provider(provider)
    latest_test = db.scalar(
        select(LLMProviderTestRun)
        .where(LLMProviderTestRun.provider_id == provider.id)
        .order_by(LLMProviderTestRun.created_at.desc(), LLMProviderTestRun.id.desc())
        .limit(1)
    )
    diagnostic_ready = bool(diagnostic["ready"])
    latest_test_ok = latest_test.ok if latest_test is not None else None
    last_blocker = diagnostic.get("last_blocker")
    if provider.provider_type == "mock":
        collection_ready = diagnostic_ready
        collection_blocker = None if collection_ready else "Mock Provider 配置不完整。"
    elif last_blocker:
        collection_ready = False
        collection_blocker = f"渠道存在历史 blocker：{last_blocker}。"
    elif not diagnostic_ready:
        collection_ready = False
        missing = "、".join(str(item) for item in diagnostic["missing"]) or "必要配置"
        collection_blocker = f"Provider 配置未完成：{missing}。"
    elif latest_test_ok is not True:
        collection_ready = False
        collection_blocker = (
            f"最近一次测试失败：{latest_test.error_message or '未知错误'}。"
            if latest_test is not None
            else "真实 Provider 尚未通过测试调用。"
        )
    else:
        collection_ready = True
        collection_blocker = None
    tasks = [
        task
        for task in db.scalars(select(CrawlTask).order_by(CrawlTask.started_at.desc().nullslast(), CrawlTask.id.desc()))
        if provider_id in (task.provider_ids or [])
    ]
    latest_task = tasks[0] if tasks else None
    result_row = db.execute(
        select(
            func.count(CrawlResult.id),
            func.max(CrawlResult.id),
            func.max(CrawlResult.collected_at),
        ).where(CrawlResult.provider_id == provider_id)
    ).one()
    usage_row = db.execute(
        select(
            func.count(UsageRecord.id),
            func.coalesce(func.sum(UsageRecord.total_tokens), 0),
        ).where(UsageRecord.provider_id == provider_id, UsageRecord.action == "crawl.answer")
    ).one()
    latest_result = db.scalar(
        select(CrawlResult)
        .where(CrawlResult.provider_id == provider_id)
        .order_by(CrawlResult.collected_at.desc().nullslast(), CrawlResult.id.desc())
        .limit(1)
    )
    return LLMProviderCollectionSummary(
        provider_id=provider_id,
        collection_ready=collection_ready,
        collection_blocker=collection_blocker,
        diagnostic_ready=diagnostic_ready,
        latest_test_ok=latest_test_ok,
        latest_test_error=latest_test.error_message if latest_test is not None else None,
        latest_test_created_at=latest_test.created_at if latest_test is not None else None,
        total_task_count=len(tasks),
        success_task_count=sum(1 for task in tasks if task.status == "success"),
        failed_task_count=sum(1 for task in tasks if task.status == "failed"),
        result_count=int(result_row[0] or 0),
        usage_record_count=int(usage_row[0] or 0),
        total_tokens=int(usage_row[1] or 0),
        latest_task_id=latest_task.id if latest_task else None,
        latest_task_project_id=latest_task.project_id if latest_task else None,
        latest_task_type=latest_task.task_type if latest_task else None,
        latest_task_status=latest_task.status if latest_task else None,
        latest_task_started_at=latest_task.started_at if latest_task else None,
        latest_task_finished_at=latest_task.finished_at if latest_task else None,
        latest_task_error_message=latest_task.error_message if latest_task else None,
        latest_result_id=latest_result.id if latest_result else None,
        latest_result_project_id=latest_result.project_id if latest_result else None,
        latest_result_collected_at=latest_result.collected_at if latest_result else None,
    )


@router.post("", response_model=LLMProviderRead, status_code=201)
def create_provider(
    payload: LLMProviderCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
) -> LLMProvider:
    data = payload.model_dump()
    data["auth_config"] = normalize_provider_auth_config(data.get("auth_config"))
    provider = LLMProvider(**data)
    db.add(provider)
    db.flush()
    record_audit_log(
        db,
        user=user,
        action="provider.create",
        resource_type="llm_provider",
        resource_id=provider.id,
        detail={"provider_type": provider.provider_type, "model_name": provider.model_name},
    )
    db.commit()
    db.refresh(provider)
    return provider


@router.patch("/{provider_id}", response_model=LLMProviderRead)
def update_provider(
    provider_id: int,
    payload: LLMProviderUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
) -> LLMProvider:
    provider = get_provider_or_404(db, provider_id)
    update_data = payload.model_dump(exclude_unset=True)
    if "auth_config" in update_data:
        update_data["auth_config"] = normalize_provider_auth_config(
            update_data["auth_config"],
            existing=provider.auth_config,
        )
    for field, value in update_data.items():
        setattr(provider, field, value)
    record_audit_log(
        db,
        user=user,
        action="provider.update",
        resource_type="llm_provider",
        resource_id=provider.id,
        detail={"updated_fields": list(update_data.keys())},
    )
    db.commit()
    db.refresh(provider)
    return provider


@router.post("/{provider_id}/test", response_model=LLMProviderTestResult)
def test_provider(
    provider_id: int,
    payload: LLMProviderTestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
) -> LLMProviderTestResult:
    provider = get_provider_or_404(db, provider_id)
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
            # Real provider-side Web Search regularly takes longer than 45 seconds.
            # Respect the saved channel timeout while keeping a bounded server maximum.
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
        return LLMProviderTestResult(
            id=test_run.id,
            provider_id=provider.id,
            actor_user_id=user.id,
            ok=True,
            prompt_text=answer.prompt_text,
            company_name=payload.company_name,
            industry=payload.industry,
            answer_summary=answer.answer_summary,
            raw_answer_preview=answer.raw_answer[:1000],
            latency_ms=latency_ms,
            created_at=test_run.created_at,
        )
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
        alert = create_provider_failure_alert(
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
        return LLMProviderTestResult(
            id=test_run.id,
            provider_id=provider.id,
            actor_user_id=user.id,
            ok=False,
            prompt_text=payload.prompt_text,
            company_name=payload.company_name,
            industry=payload.industry,
            error_message=str(exc),
            latency_ms=latency_ms,
            created_at=test_run.created_at,
        )


@router.post("/{provider_id}/test-jobs", response_model=QueueJobRead, status_code=202)
def enqueue_provider_test_job(
    provider_id: int,
    payload: LLMProviderTestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
) -> QueueJob:
    provider = get_provider_or_404(db, provider_id)
    diagnostic = diagnose_provider(provider)
    if not diagnostic["auth_ready"]:
        raise HTTPException(status_code=400, detail="请先保存 API Key，再测试渠道。")
    job = QueueJob(
        job_type="llm_provider.test",
        status="pending",
        priority=20,
        scheduled_at=datetime.now(UTC),
        max_attempts=1,
        payload_json={
            "project_id": 0,
            "provider_id": provider.id,
            "actor_user_id": user.id,
            "prompt_text": payload.prompt_text,
            "company_name": payload.company_name,
            "industry": payload.industry,
            "stage": "queued",
        },
    )
    db.add(job)
    db.flush()
    record_audit_log(
        db,
        user=user,
        action="provider.test.enqueue",
        resource_type="llm_provider",
        resource_id=provider.id,
        detail={"queue_job_id": job.id, "prompt_text": payload.prompt_text},
    )
    db.commit()
    db.refresh(job)
    return job


@router.get("/{provider_id}/test-jobs/{job_id}", response_model=QueueJobRead)
def get_provider_test_job(
    provider_id: int,
    job_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles("super_admin")),
) -> QueueJob:
    get_provider_or_404(db, provider_id)
    job = db.get(QueueJob, job_id)
    if (
        job is None
        or job.job_type != "llm_provider.test"
        or int((job.payload_json or {}).get("provider_id") or 0) != provider_id
    ):
        raise HTTPException(status_code=404, detail="Provider test job not found")
    return job


@router.get("/{provider_id}/test-runs", response_model=list[LLMProviderTestResult])
def list_provider_test_runs(
    provider_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles("super_admin")),
) -> list[LLMProviderTestRun]:
    get_provider_or_404(db, provider_id)
    return list(
        db.scalars(
            select(LLMProviderTestRun)
            .where(LLMProviderTestRun.provider_id == provider_id)
            .order_by(LLMProviderTestRun.created_at.desc())
            .limit(20)
        )
    )


@router.delete("/{provider_id}", response_model=APIMessage)
def delete_provider(
    provider_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
) -> APIMessage:
    provider = get_provider_or_404(db, provider_id)
    record_audit_log(
        db,
        user=user,
        action="provider.delete",
        resource_type="llm_provider",
        resource_id=provider.id,
        detail={"provider_type": provider.provider_type, "model_name": provider.model_name},
    )
    db.delete(provider)
    db.commit()
    return APIMessage(message="LLM provider deleted")
