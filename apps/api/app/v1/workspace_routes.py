import hmac
import secrets
from datetime import datetime, timezone
from hashlib import sha256
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import WRITE_ROLES, assert_company_access, get_current_user, require_roles
from app.core.config import get_settings
from app.db.session import get_db
from app.models import AuditLog, Company, LLMProvider, Project
from app.models.cleanroom_v1 import (
    GeoBrowserAccount,
    GeoEvidence,
    GeoObservationBatch,
    GeoObservationRun,
    GeoObservationTask,
    GeoQuestionPlan,
    GeoSamplingBatch,
    GeoSamplingSample,
    GeoWorkspace,
)
from app.models.user import User
from app.models.workspace_access import WorkspaceMembership
from app.services.article_sync_adapter import get_article_sync_adapter
from app.services.audit import record_audit_log
from app.services.llm_provider import diagnose_provider, get_search_provider
from app.services.worker_heartbeat import get_workspace_worker_status
from app.services.worker_service import inspect_managed_worker_service
from app.services.workspace_access import add_membership, require_workspace_manager
from app.services.workspace_secrets import (
    ARTICLE_SYNC_MCP_TOKEN,
    DEEPSEEK_API_KEY,
    get_workspace_secret,
    resolve_article_sync_credentials,
    secret_status,
    set_workspace_secret,
)
from app.v1.observation_service import (
    question_sampling_eligible as _question_sampling_eligible,
    refresh_observation_ledger_batch as _refresh_observation_ledger_batch,
    write_scorecard,
)
from app.v1.route_support import scoped_or_404, workspace_or_404
from app.v1.schemas import (
    BrowserAccountCreate,
    BrowserAccountLeaseRead,
    BrowserAccountLeaseRequest,
    BrowserAccountRead,
    BrowserAccountReleaseRequest,
    BrowserAccountUpdate,
    QueueWorkerStatusRead,
    SamplingBatchCreate,
    SamplingBatchRead,
    SamplingWorkerClaimRead,
    SamplingWorkerClaimRequest,
    SamplingWorkerComplete,
    SamplingWorkerFail,
    WorkspaceCreate,
    WorkspaceIntegrationRead,
    WorkspaceIntegrationTestRequest,
    WorkspaceIntegrationUpdate,
    WorkspaceRead,
    WorkspaceUpdate,
    YaoDatasetImport,
)


router = APIRouter(prefix="/v1", tags=["geo-workspaces-v1"])


def _lease_hash(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def _lease_matches(account: GeoBrowserAccount, token: str) -> bool:
    return bool(
        account.lease_token_hash
        and hmac.compare_digest(account.lease_token_hash, _lease_hash(token))
    )


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _clear_lease(account: GeoBrowserAccount) -> None:
    account.lease_token_hash = None
    account.lease_worker_id = None
    account.lease_run_id = None
    account.lease_expires_at = None


def _account_for_import(
    db: Session,
    workspace_id: int,
    payload: YaoDatasetImport,
    target_run_id: int | None,
) -> GeoBrowserAccount | None:
    if payload.browser_account_id is None and payload.lease_token is None:
        return None
    if payload.browser_account_id is None or payload.lease_token is None:
        raise HTTPException(
            status_code=422, detail="browser_account_id and lease_token must be provided together"
        )
    account = scoped_or_404(db, GeoBrowserAccount, workspace_id, payload.browser_account_id)
    if account.provider_key != payload.platform:
        raise HTTPException(
            status_code=422, detail="Browser account provider does not match the imported platform"
        )
    if account.status != "busy" or not _lease_matches(account, payload.lease_token):
        raise HTTPException(
            status_code=409, detail="Browser account lease is invalid or no longer active"
        )
    if account.lease_expires_at is None or _as_utc(account.lease_expires_at) <= datetime.now(
        timezone.utc
    ):
        raise HTTPException(status_code=409, detail="Browser account lease has expired")
    if account.lease_run_id is not None and account.lease_run_id != target_run_id:
        raise HTTPException(
            status_code=409, detail="Browser account lease belongs to another observation run"
        )
    return account


@router.get("/workspaces/{workspace_id}/browser-accounts", response_model=list[BrowserAccountRead])
def list_browser_accounts(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    return list(
        db.scalars(
            select(GeoBrowserAccount)
            .where(
                GeoBrowserAccount.workspace_id == workspace_id,
                GeoBrowserAccount.provider_key == "deepseek",
            )
            .order_by(GeoBrowserAccount.alias)
        )
    )


@router.post(
    "/workspaces/{workspace_id}/browser-accounts",
    response_model=BrowserAccountRead,
    status_code=201,
)
def create_browser_account(
    workspace_id: int,
    payload: BrowserAccountCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    account = GeoBrowserAccount(
        workspace_id=workspace_id,
        provider_key="deepseek",
        alias=payload.alias,
        ego_task_space_id=payload.ego_task_space_id,
        browser_profile_alias=payload.browser_profile_alias,
        cohort=payload.cohort,
        status="onboarding",
        health_note="等待首次登录验证",
    )
    db.add(account)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="账号别名或独立浏览器身份已存在") from exc
    db.refresh(account)
    return account


@router.patch(
    "/workspaces/{workspace_id}/browser-accounts/{account_id}", response_model=BrowserAccountRead
)
def update_browser_account(
    workspace_id: int,
    account_id: int,
    payload: BrowserAccountUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    account = scoped_or_404(db, GeoBrowserAccount, workspace_id, account_id)
    account.status = payload.status
    account.health_note = payload.health_note
    if payload.cohort is not None:
        account.cohort = payload.cohort
    if payload.browser_profile_alias is not None:
        account.browser_profile_alias = payload.browser_profile_alias
    if payload.session_fingerprint is not None:
        account.session_fingerprint = payload.session_fingerprint
        account.isolation_verified_at = datetime.now(timezone.utc)
    if payload.status == "ready" and not (
        account.browser_profile_alias
        and account.session_fingerprint
        and account.isolation_verified_at
    ):
        raise HTTPException(status_code=422, detail="请先连接独立浏览器账号并完成隔离验证")
    account.last_checked_at = datetime.now(timezone.utc)
    if payload.status in {"ready", "reauth_required", "disabled", "onboarding"}:
        account.cooldown_until = None
        _clear_lease(account)
    if payload.status == "ready":
        account.consecutive_failures = 0
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="该浏览器 Profile 或登录会话已被其他账号占用"
        ) from exc
    db.refresh(account)
    return account


@router.post(
    "/workspaces/{workspace_id}/browser-accounts/lease", response_model=BrowserAccountLeaseRead
)
def lease_browser_account(
    workspace_id: int,
    payload: BrowserAccountLeaseRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    if payload.run_id is not None:
        scoped_or_404(db, GeoObservationRun, workspace_id, payload.run_id)
    now = datetime.now(timezone.utc)
    db.execute(
        update(GeoBrowserAccount)
        .where(
            GeoBrowserAccount.workspace_id == workspace_id,
            GeoBrowserAccount.provider_key == "deepseek",
            GeoBrowserAccount.status == "busy",
            GeoBrowserAccount.lease_expires_at <= now,
        )
        .values(
            status="ready",
            lease_token_hash=None,
            lease_worker_id=None,
            lease_run_id=None,
            lease_expires_at=None,
            health_note="过期任务已自动释放",
        )
    )
    db.execute(
        update(GeoBrowserAccount)
        .where(
            GeoBrowserAccount.workspace_id == workspace_id,
            GeoBrowserAccount.provider_key == "deepseek",
            GeoBrowserAccount.status == "cooldown",
            GeoBrowserAccount.cooldown_until <= now,
        )
        .values(status="ready", cooldown_until=None, health_note="冷却完成，可继续采样")
    )
    db.flush()
    candidate_ids = list(
        db.scalars(
            select(GeoBrowserAccount.id)
            .where(
                GeoBrowserAccount.workspace_id == workspace_id,
                GeoBrowserAccount.provider_key == "deepseek",
                GeoBrowserAccount.status == "ready",
                GeoBrowserAccount.browser_profile_alias.is_not(None),
                GeoBrowserAccount.session_fingerprint.is_not(None),
                GeoBrowserAccount.isolation_verified_at.is_not(None),
                GeoBrowserAccount.lease_token_hash.is_(None),
            )
            .order_by(GeoBrowserAccount.last_used_at.asc().nullsfirst(), GeoBrowserAccount.id)
        )
    )
    for account_id in candidate_ids:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.fromtimestamp(
            now.timestamp() + payload.lease_seconds, tz=timezone.utc
        )
        claimed = db.execute(
            update(GeoBrowserAccount)
            .where(
                GeoBrowserAccount.id == account_id,
                GeoBrowserAccount.workspace_id == workspace_id,
                GeoBrowserAccount.status == "ready",
                GeoBrowserAccount.lease_token_hash.is_(None),
            )
            .values(
                status="busy",
                lease_token_hash=_lease_hash(token),
                lease_worker_id=payload.worker_id,
                lease_run_id=payload.run_id,
                lease_expires_at=expires_at,
                last_used_at=now,
                health_note="正在执行采样任务",
            )
        )
        if claimed.rowcount == 1:
            db.commit()
            account = db.get(GeoBrowserAccount, account_id)
            return {"account": account, "lease_token": token}
    db.rollback()
    raise HTTPException(
        status_code=409, detail="当前没有可用的 DeepSeek 账号，请等待冷却或重新登录"
    )


@router.post(
    "/workspaces/{workspace_id}/browser-accounts/{account_id}/release",
    response_model=BrowserAccountRead,
)
def release_browser_account(
    workspace_id: int,
    account_id: int,
    payload: BrowserAccountReleaseRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    account = scoped_or_404(db, GeoBrowserAccount, workspace_id, account_id)
    if account.status != "busy" or not _lease_matches(account, payload.lease_token):
        raise HTTPException(
            status_code=409, detail="Browser account lease is invalid or no longer active"
        )
    now = datetime.now(timezone.utc)
    account.last_checked_at = now
    account.health_note = payload.health_note
    if payload.outcome == "success":
        account.status = "ready"
        account.consecutive_failures = 0
        account.health_note = payload.health_note or "最近一次采样成功"
    elif payload.outcome == "auth_expired":
        account.status = "reauth_required"
        account.consecutive_failures += 1
        account.health_note = payload.health_note or "登录已失效，请重新登录"
    else:
        seconds = payload.cooldown_seconds or (900 if payload.outcome == "rate_limited" else 300)
        account.status = "cooldown"
        account.cooldown_until = datetime.fromtimestamp(now.timestamp() + seconds, tz=timezone.utc)
        account.consecutive_failures += 1
        account.health_note = payload.health_note or (
            "平台限流，账号正在冷却"
            if payload.outcome == "rate_limited"
            else "采样异常，短暂冷却后重试"
        )
    _clear_lease(account)
    db.commit()
    db.refresh(account)
    return account


def _batch_read(db: Session, batch: GeoSamplingBatch) -> dict:
    samples = list(
        db.scalars(
            select(GeoSamplingSample)
            .where(GeoSamplingSample.batch_id == batch.id)
            .order_by(GeoSamplingSample.id)
        )
    )
    return {
        "id": batch.id,
        "workspace_id": batch.workspace_id,
        "run_id": batch.run_id,
        "provider_key": batch.provider_key,
        "status": batch.status,
        "account_count": batch.account_count,
        "question_count": batch.question_count,
        "repeat_count": batch.repeat_count,
        "total_samples": batch.total_samples,
        "completed_samples": batch.completed_samples,
        "failed_samples": batch.failed_samples,
        "configuration": batch.configuration,
        "current_message": batch.current_message,
        "failure_reason": batch.failure_reason,
        "started_at": batch.started_at,
        "completed_at": batch.completed_at,
        "samples": samples,
    }


def _refresh_batch(db: Session, batch: GeoSamplingBatch) -> None:
    completed = int(
        db.scalar(
            select(func.count())
            .select_from(GeoSamplingSample)
            .where(GeoSamplingSample.batch_id == batch.id, GeoSamplingSample.status == "completed")
        )
        or 0
    )
    failed = int(
        db.scalar(
            select(func.count())
            .select_from(GeoSamplingSample)
            .where(GeoSamplingSample.batch_id == batch.id, GeoSamplingSample.status == "failed")
        )
        or 0
    )
    running = int(
        db.scalar(
            select(func.count())
            .select_from(GeoSamplingSample)
            .where(GeoSamplingSample.batch_id == batch.id, GeoSamplingSample.status == "running")
        )
        or 0
    )
    batch.completed_samples = completed
    batch.failed_samples = failed
    batch.current_message = f"已完成 {completed}/{batch.total_samples}，失败 {failed}"
    run = db.get(GeoObservationRun, batch.run_id)
    if completed + failed >= batch.total_samples:
        batch.status = "completed" if failed == 0 else "partial"
        batch.completed_at = datetime.now(timezone.utc)
        if run is not None:
            run.status = batch.status
            run.completed_at = batch.completed_at
    elif completed or failed or running:
        batch.status = "running"
        batch.started_at = batch.started_at or datetime.now(timezone.utc)
        if run is not None:
            run.status = "running"
            run.started_at = run.started_at or batch.started_at
    if batch.observation_ledger_batch_id is not None:
        _refresh_observation_ledger_batch(db, batch.observation_ledger_batch_id)


@router.post(
    "/workspaces/{workspace_id}/sampling-batches", response_model=SamplingBatchRead, status_code=202
)
def create_sampling_batch(
    workspace_id: int,
    payload: SamplingBatchCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    raise HTTPException(
        status_code=410,
        detail="DeepSeek 网页自动采样已停用；请改用 DeepSeek 官方 API + Web Search 渠道",
    )
    active = db.scalar(
        select(GeoSamplingBatch)
        .where(
            GeoSamplingBatch.workspace_id == workspace_id,
            GeoSamplingBatch.status.in_(("queued", "running")),
        )
        .order_by(GeoSamplingBatch.id.desc())
    )
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail=f"已有测试正在进行（{active.completed_samples}/{active.total_samples}）",
        )
    accounts = list(
        db.scalars(
            select(GeoBrowserAccount)
            .where(
                GeoBrowserAccount.workspace_id == workspace_id,
                GeoBrowserAccount.provider_key == "deepseek",
                GeoBrowserAccount.status == "ready",
                GeoBrowserAccount.browser_profile_alias.is_not(None),
                GeoBrowserAccount.session_fingerprint.is_not(None),
                GeoBrowserAccount.isolation_verified_at.is_not(None),
            )
            .order_by(GeoBrowserAccount.last_used_at.asc().nullsfirst(), GeoBrowserAccount.id)
            .limit(payload.account_count)
        )
    )
    if len(accounts) != payload.account_count:
        raise HTTPException(status_code=422, detail="需要 2 个已完成独立隔离验证的 DeepSeek 账号")
    if (
        len({account.browser_profile_alias for account in accounts}) != payload.account_count
        or len({account.session_fingerprint for account in accounts}) != payload.account_count
    ):
        raise HTTPException(
            status_code=409, detail="检测到账号登录环境重复，请重新完成独立 Profile 验证"
        )
    questions = list(
        db.scalars(
            select(GeoQuestionPlan)
            .where(
                GeoQuestionPlan.workspace_id == workspace_id,
                GeoQuestionPlan.active.is_(True),
                GeoQuestionPlan.status.in_(("approved", "active")),
                GeoQuestionPlan.is_brand_query.is_(False),
            )
            .order_by(GeoQuestionPlan.importance.desc(), GeoQuestionPlan.id)
            .limit(payload.question_count)
        )
    )
    if len(questions) != payload.question_count:
        raise HTTPException(status_code=422, detail="需要至少 3 个已启用的非品牌高价值问题")
    run = GeoObservationRun(
        workspace_id=workspace_id,
        adapter_key="deepseek-profile-batch/v1",
        status="queued",
        request_context={
            "schema": "spring-yuan-deepseek-profile-batch/v1",
            "providers": [{"key": "deepseek", "label": "DeepSeek"}],
            "account_ids": [account.id for account in accounts],
            "question_plan_ids": [question.id for question in questions],
            "repeat_count": payload.repeat_count,
            "new_conversation_per_sample": True,
            "delete_conversation_after_archive": True,
        },
    )
    db.add(run)
    db.flush()
    total = payload.account_count * payload.question_count * payload.repeat_count
    ledger_batch = GeoObservationBatch(
        workspace_id=workspace_id,
        requested_by_user_id=user.id,
        source_type="browser_profile",
        status="pending",
        provider_count=1,
        question_count=len(questions),
        repeat_count=payload.repeat_count,
        total_tasks=total,
        configuration={
            "schema": "unified-observation-ledger/v1",
            "provider": {"key": "deepseek_browser", "label": "DeepSeek 网页端"},
            "account_ids": [account.id for account in accounts],
            "question_plan_ids": [question.id for question in questions],
        },
    )
    db.add(ledger_batch)
    db.flush()
    batch = GeoSamplingBatch(
        workspace_id=workspace_id,
        run_id=run.id,
        observation_ledger_batch_id=ledger_batch.id,
        provider_key="deepseek",
        status="queued",
        account_count=payload.account_count,
        question_count=payload.question_count,
        repeat_count=payload.repeat_count,
        total_samples=total,
        configuration={
            "account_ids": [account.id for account in accounts],
            "question_plan_ids": [question.id for question in questions],
        },
        current_message=f"等待后台采样，0/{total}",
    )
    db.add(batch)
    db.flush()
    for account in accounts:
        for question in questions:
            for repeat_index in range(1, payload.repeat_count + 1):
                observation_task = GeoObservationTask(
                    batch_id=ledger_batch.id,
                    workspace_id=workspace_id,
                    run_id=run.id,
                    provider_key="deepseek_browser",
                    provider_label=f"DeepSeek 网页端 · {account.alias}",
                    model_key="deepseek",
                    model_label="DeepSeek",
                    question_plan_id=question.id,
                    question_text_snapshot=question.question_text,
                    sample_key=(
                        f"browser-account:{account.id}:question:{question.id}:"
                        f"repeat:{repeat_index}"
                    ),
                    repeat_index=repeat_index,
                    repeat_count=payload.repeat_count,
                    status="pending",
                )
                db.add(observation_task)
                db.flush()
                db.add(
                    GeoSamplingSample(
                        batch_id=batch.id,
                        workspace_id=workspace_id,
                        run_id=run.id,
                        observation_task_id=observation_task.id,
                        browser_account_id=account.id,
                        question_plan_id=question.id,
                        repeat_index=repeat_index,
                        status="queued",
                    )
                )
    db.commit()
    db.refresh(batch)
    return _batch_read(db, batch)


@router.get(
    "/workspaces/{workspace_id}/sampling-batches/latest", response_model=SamplingBatchRead | None
)
def latest_sampling_batch(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    batch = db.scalar(
        select(GeoSamplingBatch)
        .where(GeoSamplingBatch.workspace_id == workspace_id)
        .order_by(GeoSamplingBatch.id.desc())
    )
    return _batch_read(db, batch) if batch is not None else None


@router.get(
    "/workspaces/{workspace_id}/sampling-batches/{batch_id}", response_model=SamplingBatchRead
)
def read_sampling_batch(
    workspace_id: int,
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    batch = scoped_or_404(db, GeoSamplingBatch, workspace_id, batch_id)
    return _batch_read(db, batch)


@router.post(
    "/workspaces/{workspace_id}/sampling-worker/claim", response_model=SamplingWorkerClaimRead
)
def claim_sampling_sample(
    workspace_id: int,
    payload: SamplingWorkerClaimRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace = workspace_or_404(db, user, workspace_id)
    now = datetime.now(timezone.utc)
    candidates = list(
        db.scalars(
            select(GeoSamplingSample)
            .where(
                GeoSamplingSample.workspace_id == workspace_id,
                GeoSamplingSample.status == "queued",
            )
            .order_by(GeoSamplingSample.batch_id, GeoSamplingSample.id)
        )
    )
    for sample in candidates:
        account = db.get(GeoBrowserAccount, sample.browser_account_id)
        if account is None or account.status != "ready" or not account.isolation_verified:
            continue
        batch = db.get(GeoSamplingBatch, sample.batch_id)
        question = db.get(GeoQuestionPlan, sample.question_plan_id)
        if batch is None or question is None or batch.status not in {"queued", "running"}:
            continue
        if not _question_sampling_eligible(question):
            continue
        token = secrets.token_urlsafe(32)
        expires_at = datetime.fromtimestamp(
            now.timestamp() + payload.lease_seconds, tz=timezone.utc
        )
        account_claim = db.execute(
            update(GeoBrowserAccount)
            .where(
                GeoBrowserAccount.id == account.id,
                GeoBrowserAccount.status == "ready",
                GeoBrowserAccount.lease_token_hash.is_(None),
            )
            .values(
                status="busy",
                lease_token_hash=_lease_hash(token),
                lease_worker_id=payload.worker_id,
                lease_run_id=sample.run_id,
                lease_expires_at=expires_at,
                last_used_at=now,
                health_note="正在后台采样",
            )
        )
        if account_claim.rowcount != 1:
            db.rollback()
            continue
        sample_claim = db.execute(
            update(GeoSamplingSample)
            .where(
                GeoSamplingSample.id == sample.id,
                GeoSamplingSample.status == "queued",
            )
            .values(status="running", attempt_count=sample.attempt_count + 1, started_at=now)
        )
        if sample_claim.rowcount != 1:
            db.rollback()
            continue
        if sample.observation_task_id is not None:
            observation_task = db.get(GeoObservationTask, sample.observation_task_id)
            if observation_task is not None:
                observation_task.status = "running"
                observation_task.attempt_count = sample.attempt_count + 1
                observation_task.started_at = observation_task.started_at or now
                observation_task.error_code = None
                observation_task.error_detail = None
        batch.status = "running"
        batch.started_at = batch.started_at or now
        batch.current_message = (
            f"正在采集：{account.alias} · {question.question_text} · 第 {sample.repeat_index} 次"
        )
        run = db.get(GeoObservationRun, sample.run_id)
        if run is not None:
            run.status = "running"
            run.started_at = run.started_at or now
        db.commit()
        return {
            "sample_id": sample.id,
            "batch_id": sample.batch_id,
            "run_id": sample.run_id,
            "account_id": account.id,
            "account_alias": account.alias,
            "browser_profile_alias": account.browser_profile_alias,
            "cohort": account.cohort,
            "brand_name": workspace.brand_name,
            "brand_aliases": workspace.brand_aliases,
            "question_plan_id": question.id,
            "question": question.question_text,
            "repeat_index": sample.repeat_index,
            "lease_token": token,
        }
    raise HTTPException(
        status_code=409, detail="当前没有可领取的采样；账号可能正在冷却或需要重新登录"
    )


@router.post(
    "/workspaces/{workspace_id}/sampling-worker/samples/{sample_id}/complete",
    response_model=SamplingBatchRead,
)
def complete_sampling_sample(
    workspace_id: int,
    sample_id: int,
    payload: SamplingWorkerComplete,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    sample = scoped_or_404(db, GeoSamplingSample, workspace_id, sample_id)
    if sample.status != "running":
        raise HTTPException(status_code=409, detail="采样不在执行中")
    account = scoped_or_404(db, GeoBrowserAccount, workspace_id, sample.browser_account_id)
    if (
        account.status != "busy"
        or account.lease_run_id != sample.run_id
        or not _lease_matches(account, payload.lease_token)
    ):
        raise HTTPException(status_code=409, detail="采样账号租约无效")
    if _as_utc(payload.conversation_deleted_at) < _as_utc(payload.captured_at):
        raise HTTPException(status_code=422, detail="必须先归档证据并删除网页会话，再完成样本")
    question = db.get(GeoQuestionPlan, sample.question_plan_id)
    answer_hash = sha256(
        f"{sample.run_id}|sampling-sample:{sample.id}|{payload.answer_text.strip()}".encode()
    ).hexdigest()
    evidence = GeoEvidence(
        workspace_id=workspace_id,
        run_id=sample.run_id,
        question_plan_id=sample.question_plan_id,
        model_key="deepseek",
        model_label="DeepSeek",
        prompt_version=question.prompt_version if question is not None else "v1",
        sample_mode="browser_assisted",
        evidence_level="auditable",
        collection_method="web_ui",
        evidence_kind="profile_worker",
        is_real_provider_evidence=True,
        brand_status=payload.brand_status,
        brand_position=payload.brand_position,
        competitor_positions=payload.competitor_positions,
        answer_text=payload.answer_text.strip(),
        answer_hash=answer_hash,
        source_items=[item.model_dump() for item in payload.references],
        sampling_environment={
            **payload.sampling_environment,
            "browser_account_id": account.id,
            "browser_account_alias": account.alias,
            "browser_account_cohort": account.cohort,
            "browser_profile_alias": account.browser_profile_alias,
            "repeat_index": sample.repeat_index,
            "sampling_sample_id": sample.id,
            "new_conversation": True,
            "conversation_deleted_after_archive": True,
        },
        raw_artifact_uri=payload.raw_artifact_uri,
        screenshot_uri=payload.screenshot_uri,
        captured_at=payload.captured_at,
    )
    db.add(evidence)
    db.flush()
    sample.status = "completed"
    sample.evidence_id = evidence.id
    sample.conversation_url = payload.conversation_url
    sample.raw_artifact_uri = payload.raw_artifact_uri
    sample.screenshot_uri = payload.screenshot_uri
    sample.completed_at = datetime.now(timezone.utc)
    sample.conversation_deleted_at = payload.conversation_deleted_at
    if sample.observation_task_id is not None:
        observation_task = db.get(GeoObservationTask, sample.observation_task_id)
        if observation_task is not None:
            observation_task.status = "completed"
            observation_task.run_id = sample.run_id
            observation_task.evidence_id = evidence.id
            observation_task.attempt_count = sample.attempt_count
            observation_task.completed_at = sample.completed_at
            observation_task.error_code = None
            observation_task.error_detail = None
    account.status = "ready"
    account.consecutive_failures = 0
    account.last_checked_at = datetime.now(timezone.utc)
    account.health_note = "最近一次采样成功"
    _clear_lease(account)
    batch = db.get(GeoSamplingBatch, sample.batch_id)
    db.flush()
    _refresh_batch(db, batch)
    write_scorecard(db, workspace_id, sample.run_id)
    db.commit()
    db.refresh(batch)
    return _batch_read(db, batch)


@router.post(
    "/workspaces/{workspace_id}/sampling-worker/samples/{sample_id}/fail",
    response_model=SamplingBatchRead,
)
def fail_sampling_sample(
    workspace_id: int,
    sample_id: int,
    payload: SamplingWorkerFail,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    sample = scoped_or_404(db, GeoSamplingSample, workspace_id, sample_id)
    account = scoped_or_404(db, GeoBrowserAccount, workspace_id, sample.browser_account_id)
    if (
        sample.status != "running"
        or account.status != "busy"
        or not _lease_matches(account, payload.lease_token)
    ):
        raise HTTPException(status_code=409, detail="采样账号租约无效")
    sample.error_code = payload.error_code
    sample.error_detail = payload.error_detail
    retry = payload.outcome in {"retryable", "rate_limited"} and sample.attempt_count < 3
    sample.status = "queued" if retry else "failed"
    sample.completed_at = None if retry else datetime.now(timezone.utc)
    if sample.observation_task_id is not None:
        observation_task = db.get(GeoObservationTask, sample.observation_task_id)
        if observation_task is not None:
            observation_task.status = "pending" if retry else "failed"
            observation_task.attempt_count = sample.attempt_count
            observation_task.error_code = payload.error_code
            observation_task.error_detail = payload.error_detail
            observation_task.completed_at = sample.completed_at
    account.consecutive_failures += 1
    account.last_checked_at = datetime.now(timezone.utc)
    if payload.outcome == "auth_expired":
        account.status = "reauth_required"
        account.health_note = "登录已失效，请重新登录一次"
    elif payload.outcome == "rate_limited":
        account.status = "cooldown"
        account.cooldown_until = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() + 900, tz=timezone.utc
        )
        account.health_note = "平台限流，15 分钟后自动恢复"
    else:
        account.status = "ready" if retry else "cooldown"
        account.health_note = "采样异常，系统将自动重试" if retry else "连续失败，已暂停账号"
        if not retry:
            account.cooldown_until = datetime.fromtimestamp(
                datetime.now(timezone.utc).timestamp() + 900, tz=timezone.utc
            )
    _clear_lease(account)
    batch = db.get(GeoSamplingBatch, sample.batch_id)
    db.flush()
    _refresh_batch(db, batch)
    db.commit()
    db.refresh(batch)
    return _batch_read(db, batch)


@router.get("/workspaces", response_model=list[WorkspaceRead])
def list_workspaces(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(GeoWorkspace)
    if user.role != "super_admin":
        active_member = (
            select(WorkspaceMembership.id)
            .where(
                WorkspaceMembership.workspace_id == GeoWorkspace.id,
                WorkspaceMembership.user_id == user.id,
                WorkspaceMembership.status == "active",
            )
            .exists()
        )
        query = query.where(active_member)
    return list(db.scalars(query.order_by(GeoWorkspace.id.desc())))


@router.get(
    "/workspaces/{workspace_id}/queue-worker-status",
    response_model=QueueWorkerStatusRead,
)
def get_queue_worker_status(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    status = get_workspace_worker_status(db, workspace_id)
    status["managed_service"] = inspect_managed_worker_service().as_dict()
    last_repair = db.scalar(
        select(AuditLog)
        .where(
            AuditLog.action == "queue_worker.repair",
            AuditLog.resource_type == "geo_workspace",
            AuditLog.resource_id == workspace_id,
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(1)
    )
    status["last_repair"] = (
        {
            **dict(last_repair.detail_json or {}),
            "repaired_at": last_repair.created_at,
        }
        if last_repair is not None
        else None
    )
    return status


@router.post("/workspaces", response_model=WorkspaceRead, status_code=201)
def create_workspace(
    payload: WorkspaceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin", "company_admin")),
):
    assert_company_access(user, payload.company_id)
    if db.scalar(select(GeoWorkspace).where(GeoWorkspace.slug == payload.slug)):
        raise HTTPException(status_code=409, detail="Workspace slug already exists")
    workspace = GeoWorkspace(**payload.model_dump())
    db.add(workspace)
    db.flush()
    add_membership(
        db,
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
    )
    db.commit()
    db.refresh(workspace)
    return workspace


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceRead)
def update_workspace(
    workspace_id: int,
    payload: WorkspaceUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace = workspace_or_404(db, user, workspace_id)
    workspace.brand_name = payload.brand_name.strip()
    workspace.brand_aliases = list(dict.fromkeys(alias.strip() for alias in payload.brand_aliases if alias.strip()))
    workspace.website_url = payload.website_url.strip() if payload.website_url and payload.website_url.strip() else None
    db.commit()
    db.refresh(workspace)
    return workspace


def _workspace_integration_read(db: Session, workspace_id: int) -> dict:
    workspace = db.get(GeoWorkspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    deepseek_row = secret_status(db, workspace_id, DEEPSEEK_API_KEY)
    mcp_token_row = secret_status(db, workspace_id, ARTICLE_SYNC_MCP_TOKEN)
    settings = get_settings()
    deepseek_provider = db.scalar(
        select(LLMProvider)
        .where(LLMProvider.provider_type == "deepseek_web_search")
        .order_by(LLMProvider.status.desc(), LLMProvider.id.desc())
    )
    deepseek_configured = bool(deepseek_row["configured"] or (deepseek_provider and diagnose_provider(deepseek_provider)["auth_ready"]))
    return {
        "workspace_id": workspace_id,
        "deepseek_api_key_configured": deepseek_configured,
        "article_sync_mcp_server_configured": bool(settings.article_sync_mcp_server_path),
        "article_sync_mcp_token_configured": bool(mcp_token_row["configured"] or settings.article_sync_mcp_token),
        "deepseek_updated_at": deepseek_row["updated_at"],
        "article_sync_mcp_updated_at": mcp_token_row["updated_at"],
    }


@router.get("/workspaces/{workspace_id}/integrations", response_model=WorkspaceIntegrationRead)
def get_workspace_integrations(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    workspace_or_404(db, user, workspace_id)
    return _workspace_integration_read(db, workspace_id)


@router.patch("/workspaces/{workspace_id}/integrations", response_model=WorkspaceIntegrationRead)
def update_workspace_integrations(
    workspace_id: int,
    payload: WorkspaceIntegrationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    require_workspace_manager(db, user, workspace_id)
    changed: list[str] = []
    if payload.deepseek_api_key and payload.deepseek_api_key.strip():
        value = payload.deepseek_api_key.strip()
        set_workspace_secret(db, workspace_id=workspace_id, key=DEEPSEEK_API_KEY, value=value, user_id=user.id)
        changed.append("deepseek_api_key")
    if payload.article_sync_mcp_token and payload.article_sync_mcp_token.strip():
        set_workspace_secret(db, workspace_id=workspace_id, key=ARTICLE_SYNC_MCP_TOKEN, value=payload.article_sync_mcp_token.strip(), user_id=user.id)
        changed.append("article_sync_mcp_token")
    if changed:
        record_audit_log(
            db,
            user=user,
            action="workspace.integrations.update",
            resource_type="geo_workspace",
            resource_id=workspace_id,
            detail={"updated_fields": changed, "secret_values_omitted": True},
        )
    db.commit()
    return _workspace_integration_read(db, workspace_id)


@router.post("/workspaces/{workspace_id}/integrations/test")
def test_workspace_integration(
    workspace_id: int,
    payload: WorkspaceIntegrationTestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    workspace, _membership = require_workspace_manager(db, user, workspace_id)
    started_at = perf_counter()
    if payload.integration == "article_sync_mcp":
        server_path, token = resolve_article_sync_credentials(db, workspace_id)
        adapter = get_article_sync_adapter(server_path=server_path, token=token)
        try:
            result = adapter.probe()
        except RuntimeError as exc:
            error_code = str(exc)
            if error_code == "sync_adapter_not_configured":
                message = "文章同步助手 MCP 尚未配置，请先保存 MCP Server 路径和 Token。"
            elif error_code == "article_sync_extension_not_connected":
                message = "MCP Server 正在持续运行，但扩展仍未连接；请确认扩展已开启 MCP 连接，地址为 ws://localhost:9527。"
            elif error_code == "article_sync_mcp_auth_failed":
                message = "扩展已连接，但 Token 校验失败；请让扩展 Token 与当前工作区配置完全一致。"
            elif error_code == "article_sync_mcp_port_in_use":
                message = "本机 9527 端口已被其他进程占用；请关闭手动启动的 MCP Server，由 GEO 统一托管。"
            elif error_code == "article_sync_mcp_server_path_not_found":
                message = "MCP Server 文件不存在，请重新构建并保存有效的 dist/index.js 路径。"
            else:
                message = "MCP 能力发现失败，请检查 MCP Server 路径、Token、Node 和扩展连接状态。"
            return {"integration": payload.integration, "ok": False, "message": message, "latency_ms": int((perf_counter() - started_at) * 1000)}
        return {"integration": payload.integration, "ok": True, "message": "MCP 能力发现成功；未创建草稿。", "latency_ms": int((perf_counter() - started_at) * 1000), "platforms": result.get("platforms")}

    provider = db.scalar(
        select(LLMProvider)
        .where(LLMProvider.provider_type == "deepseek_web_search")
        .order_by(LLMProvider.status.desc(), LLMProvider.id.desc())
    )
    if provider is None:
        return {"integration": payload.integration, "ok": False, "message": "尚未配置 DeepSeek 内容生成渠道。"}
    workspace_api_key = get_workspace_secret(db, workspace_id, DEEPSEEK_API_KEY)
    diagnostic = diagnose_provider(provider, api_key_override=workspace_api_key)
    if not diagnostic["auth_ready"]:
        return {"integration": payload.integration, "ok": False, "message": "DeepSeek API Key 尚未配置。"}
    company = db.get(Company, workspace.company_id) or Company(name=workspace.brand_name, industry="", website_url=workspace.website_url, brand_aliases=workspace.brand_aliases)
    project = db.scalar(select(Project).where(Project.company_id == workspace.company_id).order_by(Project.id.desc())) or Project(company_id=workspace.company_id, name="内容生成连通性测试", target_industry=company.industry, target_audience="企业读者")
    try:
        answer = get_search_provider(provider, api_key_override=workspace_api_key).answer("请返回一句‘DeepSeek 内容生成连通性测试通过’，不要扩展。", company, project, [])
    except Exception as exc:
        return {"integration": payload.integration, "ok": False, "message": f"DeepSeek 请求失败：{str(exc)[:180]}", "latency_ms": int((perf_counter() - started_at) * 1000)}
    return {"integration": payload.integration, "ok": bool(answer.raw_answer.strip()), "message": "DeepSeek 内容生成请求已返回；未写入草稿。", "latency_ms": int((perf_counter() - started_at) * 1000)}
