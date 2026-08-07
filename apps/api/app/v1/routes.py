from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
from pathlib import Path
import secrets
from time import perf_counter
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import WRITE_ROLES, assert_company_access, get_current_user, require_roles
from app.core.config import get_settings
from app.db.session import get_db
from app.models import Company, LLMProvider, LLMProviderTestRun, Project, QueueJob
from app.models.cleanroom_v1 import (
    GeoActionEvent,
    GeoActionOpportunity,
    GeoActionOpportunityEvidence,
    GeoBrandFact,
    GeoBrowserAccount,
    GeoContentAudit,
    GeoContentAsset,
    GeoContentBrief,
    GeoDistributionRun,
    GeoDistributionTarget,
    GeoPlatformVariant,
    GeoEvidence,
    GeoObservationBatch,
    GeoObservationRun,
    GeoObservationTask,
    GeoOptimizationAction,
    GeoQuestionPlan,
    GeoQuestionReview,
    GeoReobservation,
    GeoSamplingBatch,
    GeoSamplingSample,
    GeoScorecard,
    GeoWorkspace,
)
from app.models.user import User
from app.schemas.search import QueueJobRead
from app.v1.schemas import (
    ActionCreate,
    ActionEvidenceSummaryRead,
    ActionEventRead,
    ActionOpportunityDiscoverRequest,
    ActionOpportunityRead,
    ActionRead,
    ActionStageUpdate,
    ActionUpdate,
    BrandFactCreate,
    BrandFactRead,
    ContentAuditCreate,
    BrowserAccountCreate,
    BrowserAccountLeaseRead,
    BrowserAccountLeaseRequest,
    BrowserAccountRead,
    BrowserAccountReleaseRequest,
    BrowserAccountUpdate,
    CompetitorComparisonRead,
    CompetitorInsightRead,
    CompetitorInsightRequest,
    ContentAuditRead,
    ContentBriefCreate,
    ContentBriefRead,
    ContentAssetRead,
    ContentGenerateRequest,
    DistributionRunCreate,
    DistributionRunRead,
    PlatformVariantCreate,
    PlatformVariantRead,
    DecisionMapRead,
    EvidenceRead,
    QuestionLibraryRead,
    QuestionAnalysisRead,
    QuestionPlanAction,
    QuestionPlanCreate,
    QuestionPlanMerge,
    QuestionPlanRead,
    QuestionPlanUpdate,
    QuestionReviewRead,
    OfficialApiObservationBatchCreate,
    OfficialApiObservationBatchListRead,
    OfficialApiObservationBatchRead,
    OfficialApiObservationJobStatus,
    ObservationLedgerListRead,
    OfficialApiObservationRequest,
    OfficialApiObservationResponse,
    QueuedOfficialApiObservationResponse,
    ReobservationCreate,
    ScorecardRead,
    SourceMapRead,
    StandardObservationRequest,
    StandardObservationResponse,
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
    YaoDeepSeekDatasetImport,
    YaoDoubaoDatasetImport,
)
from app.services.llm_provider import diagnose_provider, get_search_provider
from app.services.audit import record_audit_log
from app.services.usage import enforce_monthly_search_budget, record_usage
from app.v1.competitor_comparison import build_competitor_comparison
from app.v1.competitor_insight import CompetitorInsightError, generate_competitor_insight
from app.v1.evidence_analysis import analyze_brand_status
from app.v1.scoring import SCORING_VERSION, audit_content_snapshot, score_evidence
from app.v1.source_map import build_source_map
from app.v1.question_analysis import build_question_analysis
from app.v1.yao_adapter import normalize_yao_stage1_dataset
from app.v1.action_opportunities import discover_opportunities
from app.v1.platform_adaptation import adapt_asset
from app.services.article_sync_adapter import get_article_sync_adapter
from app.services.workspace_secrets import (
    ARTICLE_SYNC_MCP_TOKEN,
    ARTICLE_SYNC_MCP_SERVER_PATH,
    DEEPSEEK_API_KEY,
    get_workspace_secret,
    resolve_article_sync_credentials,
    secret_status,
    set_workspace_secret,
)


router = APIRouter(prefix="/v1", tags=["clean-room-geo-v1"])

API_ROOT = Path(__file__).resolve().parents[2]
OFFICIAL_API_ARTIFACT_ROOT = API_ROOT / "private_artifacts" / "official_api"


def workspace_or_404(db: Session, user: User, workspace_id: int) -> GeoWorkspace:
    workspace = db.get(GeoWorkspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_company_access(user, workspace.company_id)
    return workspace


def scoped_or_404(db: Session, model: type, workspace_id: int, item_id: int):
    item = db.get(model, item_id)
    if item is None or item.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Resource not found")
    return item


def write_scorecard(db: Session, workspace_id: int, run_id: int) -> GeoScorecard:
    evidence = list(
        db.scalars(
            select(GeoEvidence).where(
                GeoEvidence.workspace_id == workspace_id, GeoEvidence.run_id == run_id
            )
        )
    )
    metrics, explanation, fingerprint = score_evidence(evidence)
    scorecard = GeoScorecard(
        workspace_id=workspace_id,
        run_id=run_id,
        scoring_version=SCORING_VERSION,
        input_fingerprint=fingerprint,
        metrics=metrics,
        explanation=explanation,
    )
    db.add(scorecard)
    db.flush()
    return scorecard


MODEL_LABELS = {
    "deepseek": "DeepSeek",
    "doubao": "豆包",
    "kimi": "Kimi",
    "glm": "智谱 GLM",
    "qianwen": "通义千问",
    "yuanbao": "腾讯元宝",
    "hunyuan": "腾讯混元",
}

STANDARD_MODELS = (
    ("deepseek", "DeepSeek"),
    ("doubao", "豆包"),
    ("qianwen", "通义千问"),
    ("glm", "智谱 GLM"),
    ("kimi", "Kimi"),
    ("hunyuan", "腾讯混元"),
)

SEARCH_PROVIDER_TYPES = {
    "deepseek_web_search",
    "kimi_web_search",
    "hunyuan_web_search",
    "qwen_compatible",
    "bailian_qwen_responses",
    "volcengine_ark",
    "xiaoma_domestic_web_search",
}


def _provider_model_key(provider: LLMProvider) -> str:
    """Map a configured provider to the decision-map column it actually represents."""
    configured_key = str((provider.cost_rule or {}).get("platform_key") or "").strip().lower()
    aliases = {
        "qwen": "qianwen",
        "qianwen": "qianwen",
        "deepseek": "deepseek",
        "doubao": "doubao",
        "kimi": "kimi",
        "glm": "glm",
        "hunyuan": "hunyuan",
    }
    if configured_key in aliases:
        return aliases[configured_key]
    value = f"{provider.name} {provider.provider_type} {provider.model_name}".lower()
    if "doubao" in value or "豆包" in value:
        return "doubao"
    if "kimi" in value or "moonshot" in value:
        return "kimi"
    if "glm" in value or "智谱" in value or "zhipu" in value:
        return "glm"
    if "qwen" in value or "千问" in value or "dashscope" in value:
        return "qianwen"
    if "hunyuan" in value or "混元" in value:
        return "hunyuan"
    return "deepseek"


def _provider_model_label(provider: LLMProvider, model_key: str) -> str:
    labels = {
        "deepseek": "DeepSeek",
        "doubao": "豆包",
        "qianwen": "通义千问",
        "kimi": "Kimi",
        "glm": "智谱 GLM",
        "hunyuan": "腾讯混元",
    }
    label = labels.get(model_key, provider.name)
    transport = "聚合 API" if provider.provider_type == "xiaoma_domestic_web_search" else "官方 API"
    return f"{label} · {transport} + 联网搜索"


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


def _refresh_observation_ledger_batch(db: Session, batch_id: int) -> None:
    """Derive batch progress from persisted task rows, never from UI state."""

    batch = db.get(GeoObservationBatch, batch_id)
    if batch is None:
        return
    completed = int(
        db.scalar(
            select(func.count())
            .select_from(GeoObservationTask)
            .where(
                GeoObservationTask.batch_id == batch_id,
                GeoObservationTask.status == "completed",
            )
        )
        or 0
    )
    failed = int(
        db.scalar(
            select(func.count())
            .select_from(GeoObservationTask)
            .where(
                GeoObservationTask.batch_id == batch_id,
                GeoObservationTask.status == "failed",
            )
        )
        or 0
    )
    running = int(
        db.scalar(
            select(func.count())
            .select_from(GeoObservationTask)
            .where(
                GeoObservationTask.batch_id == batch_id,
                GeoObservationTask.status == "running",
            )
        )
        or 0
    )
    batch.completed_tasks = completed
    batch.failed_tasks = failed
    if completed + failed >= batch.total_tasks and batch.total_tasks > 0:
        batch.status = "completed" if failed == 0 else "partial"
        batch.completed_at = batch.completed_at or datetime.now(timezone.utc)
    elif completed or failed or running:
        batch.status = "running"
        batch.started_at = batch.started_at or datetime.now(timezone.utc)
        batch.completed_at = None
    else:
        batch.status = "pending"
        batch.completed_at = None
    db.add(batch)


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
        query = query.where(GeoWorkspace.company_id == user.company_id)
    return list(db.scalars(query.order_by(GeoWorkspace.id.desc())))


@router.post("/workspaces", response_model=WorkspaceRead, status_code=201)
def create_workspace(
    payload: WorkspaceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    assert_company_access(user, payload.company_id)
    if db.scalar(select(GeoWorkspace).where(GeoWorkspace.slug == payload.slug)):
        raise HTTPException(status_code=409, detail="Workspace slug already exists")
    workspace = GeoWorkspace(**payload.model_dump())
    db.add(workspace)
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
    mcp_server_path_row = secret_status(db, workspace_id, ARTICLE_SYNC_MCP_SERVER_PATH)
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
        "article_sync_mcp_server_path": get_workspace_secret(db, workspace_id, ARTICLE_SYNC_MCP_SERVER_PATH) or settings.article_sync_mcp_server_path,
        "article_sync_mcp_token_configured": bool(mcp_token_row["configured"] or settings.article_sync_mcp_token),
        "deepseek_updated_at": deepseek_row["updated_at"],
        "article_sync_mcp_updated_at": mcp_token_row["updated_at"] or mcp_server_path_row["updated_at"],
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
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> dict:
    workspace_or_404(db, user, workspace_id)
    changed: list[str] = []
    if payload.deepseek_api_key and payload.deepseek_api_key.strip():
        value = payload.deepseek_api_key.strip()
        set_workspace_secret(db, workspace_id=workspace_id, key=DEEPSEEK_API_KEY, value=value, user_id=user.id)
        provider = db.scalar(
            select(LLMProvider)
            .where(LLMProvider.provider_type == "deepseek_web_search")
            .order_by(LLMProvider.status.desc(), LLMProvider.id.desc())
        )
        if provider is None:
            provider = LLMProvider(
                name="DeepSeek 官方内容生成",
                provider_type="deepseek_web_search",
                api_base_url="https://api.deepseek.com/anthropic",
                model_name="deepseek-v4-flash",
                auth_config={},
                cost_rule={"channel_role": "official", "platform_key": "deepseek"},
                status="active",
            )
            db.add(provider)
            db.flush()
        from app.services.workspace_secrets import encrypt_secret

        provider.auth_config = {
            **(provider.auth_config or {}),
            "api_key_encrypted": encrypt_secret(value),
            "api_key_configured": True,
        }
        provider.auth_config.pop("api_key", None)
        changed.append("deepseek_api_key")
    if payload.article_sync_mcp_server_path and payload.article_sync_mcp_server_path.strip():
        set_workspace_secret(db, workspace_id=workspace_id, key=ARTICLE_SYNC_MCP_SERVER_PATH, value=payload.article_sync_mcp_server_path.strip(), user_id=user.id)
        changed.append("article_sync_mcp_server_path")
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
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> dict:
    workspace = workspace_or_404(db, user, workspace_id)
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
    diagnostic = diagnose_provider(provider)
    if not diagnostic["auth_ready"]:
        return {"integration": payload.integration, "ok": False, "message": "DeepSeek API Key 尚未配置。"}
    company = db.get(Company, workspace.company_id) or Company(name=workspace.brand_name, industry="", website_url=workspace.website_url, brand_aliases=workspace.brand_aliases)
    project = db.scalar(select(Project).where(Project.company_id == workspace.company_id).order_by(Project.id.desc())) or Project(company_id=workspace.company_id, name="内容生成连通性测试", target_industry=company.industry, target_audience="企业读者")
    try:
        answer = get_search_provider(provider).answer("请返回一句‘DeepSeek 内容生成连通性测试通过’，不要扩展。", company, project, [])
    except Exception as exc:
        return {"integration": payload.integration, "ok": False, "message": f"DeepSeek 请求失败：{str(exc)[:180]}", "latency_ms": int((perf_counter() - started_at) * 1000)}
    return {"integration": payload.integration, "ok": bool(answer.raw_answer.strip()), "message": "DeepSeek 内容生成请求已返回；未写入草稿。", "latency_ms": int((perf_counter() - started_at) * 1000)}


QUESTION_STAGES = ("awareness", "consideration", "decision")
QUESTION_ROLES = ("ciso", "technical_lead", "procurement")
QUESTION_STATUSES = ("draft", "pending_review", "approved", "active", "deprecated", "rejected")


def _question_snapshot(plan: GeoQuestionPlan) -> dict:
    return {
        "id": plan.id,
        "question_text": plan.question_text,
        "journey_stage": plan.journey_stage,
        "role": plan.role,
        "topic_tags": plan.topic_tags or [],
        "importance": plan.importance,
        "status": plan.status,
        "version": plan.version,
        "source_type": plan.source_type,
        "source_evidence": plan.source_evidence or {},
        "source_reason": plan.source_reason,
        "template_variables": plan.template_variables or [],
    }


def _record_question_review(
    db: Session,
    plan: GeoQuestionPlan,
    user: User,
    action: str,
    from_status: str | None,
    note: str | None,
) -> None:
    db.add(
        GeoQuestionReview(
            workspace_id=plan.workspace_id,
            question_plan_id=plan.id,
            actor_user_id=user.id,
            action=action,
            from_status=from_status,
            to_status=plan.status,
            note=note,
            snapshot=_question_snapshot(plan),
        )
    )


def _question_sampling_eligible(plan: GeoQuestionPlan) -> bool:
    return plan.active and plan.status in {"approved", "active"} and not plan.is_brand_query


@router.get("/workspaces/{workspace_id}/question-library", response_model=QuestionLibraryRead)
def read_question_library(
    workspace_id: int,
    search: str | None = Query(default=None, max_length=200),
    status: str | None = Query(default=None, max_length=32),
    stage: str | None = Query(default=None, max_length=40),
    role: str | None = Query(default=None, max_length=60),
    topic: str | None = Query(default=None, max_length=80),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace = workspace_or_404(db, user, workspace_id)
    query = select(GeoQuestionPlan).where(GeoQuestionPlan.workspace_id == workspace_id)
    if status and status in QUESTION_STATUSES:
        query = query.where(GeoQuestionPlan.status == status)
    if stage and stage in QUESTION_STAGES:
        query = query.where(GeoQuestionPlan.journey_stage == stage)
    if role and role in QUESTION_ROLES:
        query = query.where(GeoQuestionPlan.role == role)
    if search:
        needle = f"%{search.strip()}%"
        query = query.where(GeoQuestionPlan.question_text.ilike(needle))
    questions = list(
        db.scalars(
            query.order_by(
                GeoQuestionPlan.journey_stage,
                GeoQuestionPlan.role,
                GeoQuestionPlan.importance.desc(),
                GeoQuestionPlan.id,
            )
        )
    )
    if topic:
        questions = [question for question in questions if topic in (question.topic_tags or [])]
    all_questions = list(
        db.scalars(select(GeoQuestionPlan).where(GeoQuestionPlan.workspace_id == workspace_id))
    )
    counts = {
        value: sum(1 for item in all_questions if item.status == value)
        for value in QUESTION_STATUSES
    }
    counts["total"] = len(all_questions)
    counts["sampling_eligible"] = sum(_question_sampling_eligible(item) for item in all_questions)
    topics = sorted({topic for item in all_questions for topic in (item.topic_tags or [])})
    return {
        "workspace": workspace,
        "questions": questions,
        "counts": counts,
        "filters": {
            "search": search,
            "status": status,
            "stage": stage,
            "role": role,
            "topic": topic,
        },
        "stages": list(QUESTION_STAGES),
        "roles": list(QUESTION_ROLES),
        "topics": topics,
    }


@router.get("/workspaces/{workspace_id}/question-plans", response_model=list[QuestionPlanRead])
def list_question_plans(
    workspace_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    workspace_or_404(db, user, workspace_id)
    return list(
        db.scalars(
            select(GeoQuestionPlan)
            .where(GeoQuestionPlan.workspace_id == workspace_id)
            .order_by(GeoQuestionPlan.importance.desc(), GeoQuestionPlan.id)
        )
    )


@router.post(
    "/workspaces/{workspace_id}/question-plans", response_model=QuestionPlanRead, status_code=201
)
def create_question_plan(
    workspace_id: int,
    payload: QuestionPlanCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    data = payload.model_dump()
    if data.get("source_type") != "manual" and (
        not data.get("source_reason") or not data.get("source_evidence")
    ):
        raise HTTPException(status_code=422, detail="自动候选必须提供可读的来源理由和来源证据")
    normalized_text = data["question_text"].strip()
    duplicate = db.scalar(
        select(GeoQuestionPlan).where(
            GeoQuestionPlan.workspace_id == workspace_id,
            func.lower(GeoQuestionPlan.question_text) == normalized_text.lower(),
            GeoQuestionPlan.status != "deprecated",
        )
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=409, detail=f"问题已存在（#{duplicate.id}），请编辑现有问题或合并候选"
        )
    data["question_text"] = normalized_text
    data["status"] = "pending_review" if data.get("source_type") != "manual" else "active"
    data["source_at"] = datetime.now(timezone.utc)
    plan = GeoQuestionPlan(workspace_id=workspace_id, **data)
    db.add(plan)
    db.flush()
    _record_question_review(db, plan, user, "created", None, payload.source_reason)
    db.commit()
    db.refresh(plan)
    return plan


@router.patch(
    "/workspaces/{workspace_id}/question-plans/{question_id}", response_model=QuestionPlanRead
)
def update_question_plan(
    workspace_id: int,
    question_id: int,
    payload: QuestionPlanUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    plan = scoped_or_404(db, GeoQuestionPlan, workspace_id, question_id)
    from_status = plan.status
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if value is not None:
            setattr(plan, key, value)
    plan.version += 1
    plan.prompt_version = f"edited-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    _record_question_review(db, plan, user, "edited", from_status, None)
    db.commit()
    db.refresh(plan)
    return plan


@router.get(
    "/workspaces/{workspace_id}/question-plans/{question_id}/reviews",
    response_model=list[QuestionReviewRead],
)
def list_question_reviews(
    workspace_id: int,
    question_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    scoped_or_404(db, GeoQuestionPlan, workspace_id, question_id)
    return list(
        db.scalars(
            select(GeoQuestionReview)
            .where(
                GeoQuestionReview.workspace_id == workspace_id,
                GeoQuestionReview.question_plan_id == question_id,
            )
            .order_by(GeoQuestionReview.created_at.desc(), GeoQuestionReview.id.desc())
        )
    )


@router.post(
    "/workspaces/{workspace_id}/question-plans/{question_id}/approve",
    response_model=QuestionPlanRead,
)
def approve_question_plan(
    workspace_id: int,
    question_id: int,
    payload: QuestionPlanAction,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    plan = scoped_or_404(db, GeoQuestionPlan, workspace_id, question_id)
    from_status = plan.status
    if from_status not in {"draft", "pending_review", "rejected"}:
        raise HTTPException(status_code=409, detail="只有待审核问题可以批准")
    plan.status = "approved"
    plan.active = True
    plan.approved_by = user.id
    plan.approved_at = datetime.now(timezone.utc)
    plan.rejected_reason = None
    _record_question_review(db, plan, user, "approved", from_status, payload.note)
    db.commit()
    db.refresh(plan)
    return plan


@router.post(
    "/workspaces/{workspace_id}/question-plans/{question_id}/reject",
    response_model=QuestionPlanRead,
)
def reject_question_plan(
    workspace_id: int,
    question_id: int,
    payload: QuestionPlanAction,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    plan = scoped_or_404(db, GeoQuestionPlan, workspace_id, question_id)
    from_status = plan.status
    if from_status not in {"draft", "pending_review"}:
        raise HTTPException(status_code=409, detail="只有待审核问题可以拒绝")
    plan.status = "rejected"
    plan.active = False
    plan.rejected_reason = payload.note or "人工拒绝"
    _record_question_review(db, plan, user, "rejected", from_status, payload.note)
    db.commit()
    db.refresh(plan)
    return plan


@router.post(
    "/workspaces/{workspace_id}/question-plans/{question_id}/deprecate",
    response_model=QuestionPlanRead,
)
def deprecate_question_plan(
    workspace_id: int,
    question_id: int,
    payload: QuestionPlanAction,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    plan = scoped_or_404(db, GeoQuestionPlan, workspace_id, question_id)
    from_status = plan.status
    if from_status not in {"approved", "active"}:
        raise HTTPException(status_code=409, detail="只有已批准问题可以停用")
    plan.status = "deprecated"
    plan.active = False
    _record_question_review(db, plan, user, "deprecated", from_status, payload.note)
    db.commit()
    db.refresh(plan)
    return plan


@router.post(
    "/workspaces/{workspace_id}/question-plans/{question_id}/merge", response_model=QuestionPlanRead
)
def merge_question_plan(
    workspace_id: int,
    question_id: int,
    payload: QuestionPlanMerge,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    plan = scoped_or_404(db, GeoQuestionPlan, workspace_id, question_id)
    target = scoped_or_404(db, GeoQuestionPlan, workspace_id, payload.target_question_id)
    if plan.id == target.id:
        raise HTTPException(status_code=422, detail="不能与自身合并")
    from_status = plan.status
    plan.status = "deprecated"
    plan.active = False
    plan.similar_question_id = target.id
    plan.rejected_reason = f"已合并至问题 #{target.id}"
    _record_question_review(db, plan, user, "merged", from_status, payload.note)
    db.commit()
    db.refresh(plan)
    return plan


@router.post(
    "/workspaces/{workspace_id}/observations/standard",
    response_model=StandardObservationResponse,
    status_code=202,
)
def start_standard_observation(
    workspace_id: int,
    payload: StandardObservationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    """Create a durable, default collection request without pretending it is evidence.

    A connected collection worker is the only component allowed to turn this request into
    imported, auditable evidence. The short request shape keeps setup out of the normal UI.
    """
    workspace_or_404(db, user, workspace_id)
    questions = list(
        db.scalars(
            select(GeoQuestionPlan.id)
            .where(
                GeoQuestionPlan.workspace_id == workspace_id,
                GeoQuestionPlan.active.is_(True),
                GeoQuestionPlan.status.in_(("approved", "active")),
            )
            .order_by(GeoQuestionPlan.importance.desc(), GeoQuestionPlan.id)
        )
    )
    if not questions:
        raise HTTPException(status_code=422, detail="请先由运营同学设置至少一个高价值问题")
    run = GeoObservationRun(
        workspace_id=workspace_id,
        adapter_key="standard-observation-plan/v1",
        status="queued",
        request_context={
            "schema": "spring-yuan-standard-observation/v1",
            "question_plan_ids": questions,
            "providers": [{"key": key, "label": label} for key, label in STANDARD_MODELS],
            "repeat_count": payload.repeat_count,
            "evidence_protocol": "yao-compatible-stage1/v1",
        },
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return {
        "run": run,
        "message": "标准观测任务已创建，等待已连接的采样服务接管；任务本身不会生成或伪造结果。",
        "providers": [{"key": key, "label": label} for key, label in STANDARD_MODELS],
        "question_count": len(questions),
    }


@router.post(
    "/workspaces/{workspace_id}/observation-batches",
    response_model=OfficialApiObservationBatchRead,
    status_code=202,
)
def create_provider_web_search_batch(
    workspace_id: int,
    payload: OfficialApiObservationBatchCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    """Atomically create the exact provider x question x repeat matrix.

    The parent queue record is an orchestration receipt only. Workers claim the
    child observation jobs, while the UI polls the parent by one stable id.
    """

    workspace = workspace_or_404(db, user, workspace_id)
    providers = list(
        db.scalars(select(LLMProvider).where(LLMProvider.id.in_(payload.provider_ids)))
    )
    providers_by_id = {provider.id: provider for provider in providers}
    if len(providers_by_id) != len(payload.provider_ids):
        raise HTTPException(status_code=422, detail="部分所选模型不存在，请刷新后重试")

    questions = list(
        db.scalars(
            select(GeoQuestionPlan).where(
                GeoQuestionPlan.workspace_id == workspace_id,
                GeoQuestionPlan.id.in_(payload.question_plan_ids),
                GeoQuestionPlan.active.is_(True),
                GeoQuestionPlan.status.in_(("approved", "active")),
                GeoQuestionPlan.is_brand_query.is_(False),
            )
        )
    )
    questions_by_id = {question.id: question for question in questions}
    if len(questions_by_id) != len(payload.question_plan_ids):
        raise HTTPException(status_code=422, detail="部分所选问题已停用或不属于当前项目")

    provider_snapshots: list[dict] = []
    model_keys: set[str] = set()
    projected_calls = len(payload.question_plan_ids) * payload.repeat_count
    for provider_id in payload.provider_ids:
        provider = providers_by_id[provider_id]
        if provider.status != "active" or provider.provider_type not in SEARCH_PROVIDER_TYPES:
            raise HTTPException(
                status_code=422, detail=f"{provider.name} 未启用或不支持可审计联网搜索"
            )
        diagnostic = diagnose_provider(provider)
        if not diagnostic["ready"] or not diagnostic["supports_web_search"]:
            raise HTTPException(
                status_code=422, detail=f"{provider.name} 配置不完整或尚未启用联网搜索"
            )
        latest_test = db.scalar(
            select(LLMProviderTestRun)
            .where(
                LLMProviderTestRun.provider_id == provider.id,
            )
            .order_by(LLMProviderTestRun.created_at.desc(), LLMProviderTestRun.id.desc())
        )
        test_fresh = bool(
            latest_test is not None
            and (provider.updated_at is None or latest_test.created_at >= provider.updated_at)
        )
        if latest_test is None or latest_test.ok != True or not test_fresh:  # noqa: E712
            raise HTTPException(status_code=422, detail=f"{provider.name} 尚未通过最新联网渠道测试")
        model_key = _provider_model_key(provider)
        if model_key in model_keys:
            raise HTTPException(
                status_code=422, detail=f"同一模型平台只能选择一个渠道：{provider.name}"
            )
        model_keys.add(model_key)
        try:
            enforce_monthly_search_budget(db, provider, projected_calls=projected_calls)
        except ValueError as exc:
            raise HTTPException(status_code=429, detail=f"{provider.name}：{exc}") from exc
        provider_snapshots.append(
            {
                "id": provider.id,
                "key": model_key,
                "label": _provider_model_label(provider, model_key),
                "channel_key": provider.provider_type,
                "model_name": provider.model_name,
            }
        )

    question_snapshots = [
        {
            "id": question_id,
            "key": str(question_id),
            "label": questions_by_id[question_id].question_text,
        }
        for question_id in payload.question_plan_ids
    ]
    total = len(payload.provider_ids) * len(payload.question_plan_ids) * payload.repeat_count
    now = datetime.now(timezone.utc)
    ledger_batch = GeoObservationBatch(
        workspace_id=workspace_id,
        requested_by_user_id=user.id,
        source_type="official_api",
        status="running",
        provider_count=len(payload.provider_ids),
        question_count=len(payload.question_plan_ids),
        repeat_count=payload.repeat_count,
        total_tasks=total,
        completed_tasks=0,
        failed_tasks=0,
        configuration={
            "schema": "unified-observation-ledger/v1",
            "providers": provider_snapshots,
            "questions": question_snapshots,
        },
        started_at=now,
    )
    db.add(ledger_batch)
    db.flush()
    batch = QueueJob(
        job_type="geo_observation.batch",
        status="running",
        priority=0,
        attempts=0,
        max_attempts=1,
        scheduled_at=now,
        started_at=now,
        payload_json={
            "workspace_id": workspace_id,
            "project_id": workspace_id,
            "company_id": workspace.company_id,
            "actor_user_id": user.id,
            "provider_count": len(payload.provider_ids),
            "question_count": len(payload.question_plan_ids),
            "repeat_count": payload.repeat_count,
            "total": total,
            "providers": provider_snapshots,
            "questions": question_snapshots,
            "child_job_ids": [],
            "observation_ledger_batch_id": ledger_batch.id,
        },
    )
    db.add(batch)
    db.flush()
    ledger_batch.queue_job_id = batch.id
    db.add(ledger_batch)
    child_job_ids: list[int] = []
    # Interleave providers so a multi-model batch visibly and actually makes
    # progress across platforms. Provider-first insertion used to place every
    # DeepSeek call ahead of all other models, which made a five-model batch
    # behave like a serial one-model queue.
    observation_groups = {
        (
            provider["id"],
            question["id"],
        ): f"batch_{batch.id}_{provider['id']}_{question['id']}_{secrets.token_hex(5)}"
        for provider in provider_snapshots
        for question in question_snapshots
    }
    for repeat_index in range(1, payload.repeat_count + 1):
        for question in question_snapshots:
            for provider in provider_snapshots:
                observation_group_id = observation_groups[(provider["id"], question["id"])]
                child_payload = {
                    "workspace_id": workspace_id,
                    "project_id": workspace_id,
                    "company_id": workspace.company_id,
                    "actor_user_id": user.id,
                    "provider_id": provider["id"],
                    "provider_key": provider["key"],
                    "provider_label": provider["label"],
                    "question_plan_id": question["id"],
                    "question_label": question["label"],
                    "repeat_index": repeat_index,
                    "repeat_count": payload.repeat_count,
                    "observation_group_id": observation_group_id,
                    "observation_batch_id": batch.id,
                    "observation_ledger_batch_id": ledger_batch.id,
                }
                child = QueueJob(
                    job_type="geo_observation.collect",
                    status="pending",
                    priority=10,
                    max_attempts=3,
                    scheduled_at=now,
                    payload_json=child_payload,
                )
                db.add(child)
                db.flush()
                task = GeoObservationTask(
                    batch_id=ledger_batch.id,
                    workspace_id=workspace_id,
                    queue_job_id=child.id,
                    provider_id=provider["id"],
                    provider_key=str(provider["channel_key"]),
                    provider_label=str(provider["label"]),
                    model_key=str(provider["key"]),
                    model_label=str(provider["label"]),
                    question_plan_id=question["id"],
                    question_text_snapshot=str(question["label"]),
                    sample_key=f"provider:{provider['id']}:question:{question['id']}:repeat:{repeat_index}",
                    repeat_index=repeat_index,
                    repeat_count=payload.repeat_count,
                    observation_group_id=observation_group_id,
                    status="pending",
                )
                db.add(task)
                db.flush()
                child.payload_json = {**child_payload, "observation_task_id": task.id}
                db.add(child)
                child_job_ids.append(child.id)
    batch.payload_json = {**batch.payload_json, "child_job_ids": child_job_ids}
    db.commit()
    db.refresh(batch)
    return _official_api_batch_read(db, batch)


def _official_api_batch_state(
    db: Session, batch: QueueJob
) -> tuple[dict, list[QueueJob], dict[str, int], str, int, int]:
    batch_payload = dict(batch.payload_json or {})
    child_ids = [int(value) for value in batch_payload.get("child_job_ids") or []]
    children = (
        list(db.scalars(select(QueueJob).where(QueueJob.id.in_(child_ids)).order_by(QueueJob.id)))
        if child_ids
        else []
    )
    counts = {
        status: sum(1 for job in children if job.status == status)
        for status in ("pending", "running", "success", "failed")
    }
    settled = counts["success"] + counts["failed"]
    total = len(children) or int(batch_payload.get("total") or 0)
    if children and settled == len(children):
        status = (
            "success"
            if counts["failed"] == 0
            else "failed"
            if counts["success"] == 0
            else "partial"
        )
    elif counts["running"] or settled:
        status = "running"
    else:
        status = "pending"

    desired_parent_status = (
        "success"
        if status == "success"
        else "failed"
        if status in {"failed", "partial"}
        else "running"
    )
    state_changed = batch.status != desired_parent_status or (
        settled == len(children) and batch.finished_at is None
    )
    if state_changed:
        batch.status = desired_parent_status
        if settled == len(children):
            batch.finished_at = datetime.now(timezone.utc)
        db.add(batch)

    ledger_batch = db.scalar(
        select(GeoObservationBatch).where(GeoObservationBatch.queue_job_id == batch.id)
    )
    if ledger_batch is not None:
        ledger_status = "completed" if status == "success" else status
        ledger_changed = any(
            (
                ledger_batch.status != ledger_status,
                ledger_batch.completed_tasks != counts["success"],
                ledger_batch.failed_tasks != counts["failed"],
                ledger_batch.total_tasks != total,
            )
        )
        if ledger_changed:
            ledger_batch.status = ledger_status
            ledger_batch.completed_tasks = counts["success"]
            ledger_batch.failed_tasks = counts["failed"]
            ledger_batch.total_tasks = total
            if settled == len(children):
                ledger_batch.completed_at = batch.finished_at or datetime.now(timezone.utc)
            db.add(ledger_batch)
            state_changed = True

    if state_changed:
        db.commit()
        db.refresh(batch)
    return batch_payload, children, counts, status, settled, total


def _official_api_batch_summary(db: Session, batch: QueueJob) -> dict:
    batch_payload, _children, counts, status, settled, total = _official_api_batch_state(db, batch)
    return {
        "batch_id": batch.id,
        "status": status,
        "provider_count": int(batch_payload.get("provider_count") or 0),
        "question_count": int(batch_payload.get("question_count") or 0),
        "repeat_count": int(batch_payload.get("repeat_count") or 0),
        "total": total,
        "pending": counts["pending"],
        "running": counts["running"],
        "succeeded": counts["success"],
        "failed": counts["failed"],
        "progress_percent": round((settled / total) * 100) if total else 0,
        "status_percentages": {
            "pending": round((counts["pending"] / total) * 100) if total else 0,
            "running": round((counts["running"] / total) * 100) if total else 0,
            "succeeded": round((counts["success"] / total) * 100) if total else 0,
            "failed": round((counts["failed"] / total) * 100) if total else 0,
        },
        "created_at": batch.created_at,
        "started_at": batch.started_at,
        "finished_at": batch.finished_at,
    }


def _official_api_batch_read(
    db: Session,
    batch: QueueJob,
    *,
    task_page: int = 1,
    task_page_size: int = 125,
) -> dict:
    batch_payload, children, _counts, _status, _settled, _total = _official_api_batch_state(
        db, batch
    )

    def groups(snapshot_key: str, id_key: str) -> list[dict]:
        result: list[dict] = []
        for snapshot in batch_payload.get(snapshot_key) or []:
            matching = [
                job
                for job in children
                if int((job.payload_json or {}).get(id_key) or 0) == int(snapshot["id"])
            ]
            group_counts = {
                item: sum(1 for job in matching if job.status == item)
                for item in ("pending", "running", "success", "failed")
            }
            result.append(
                {
                    "id": int(snapshot["id"]),
                    "key": str(snapshot["key"]),
                    "label": str(snapshot["label"]),
                    "total": len(matching),
                    "pending": group_counts["pending"],
                    "running": group_counts["running"],
                    "succeeded": group_counts["success"],
                    "failed": group_counts["failed"],
                }
            )
        return result

    def duration_seconds(job: QueueJob) -> int | None:
        if job.started_at is None:
            return None
        endpoint = job.finished_at or (
            datetime.now(timezone.utc) if job.status == "running" else None
        )
        if endpoint is None:
            return None
        started_at = _as_utc(job.started_at)
        finished_at = _as_utc(endpoint)
        return max(0, round((finished_at - started_at).total_seconds()))

    task_total = len(children)
    task_start = (task_page - 1) * task_page_size
    selected_children = children[task_start : task_start + task_page_size]
    tasks = []
    for job in selected_children:
        payload = dict(job.payload_json or {})
        tasks.append(
            {
                "job_id": job.id,
                "provider_id": int(payload.get("provider_id") or 0),
                "provider_key": str(payload.get("provider_key") or "unknown"),
                "provider_label": str(payload.get("provider_label") or "未知模型"),
                "question_plan_id": int(payload.get("question_plan_id") or 0),
                "question_label": str(payload.get("question_label") or "未知问题"),
                "repeat_index": int(payload.get("repeat_index") or 1),
                "status": job.status,
                "evidence_id": int(payload["evidence_id"]) if payload.get("evidence_id") else None,
                "error_message": job.error_message,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
                "duration_seconds": duration_seconds(job),
            }
        )

    evidence_ids = [task["evidence_id"] for task in tasks if task["evidence_id"] is not None]
    errors = list(dict.fromkeys(job.error_message for job in children if job.error_message))
    return {
        **_official_api_batch_summary(db, batch),
        "provider_groups": groups("providers", "provider_id"),
        "question_groups": groups("questions", "question_plan_id"),
        "evidence_ids": evidence_ids,
        "errors": errors,
        "tasks": tasks,
        "task_pagination": {
            "page": task_page,
            "page_size": task_page_size,
            "total": task_total,
            "total_pages": (task_total + task_page_size - 1) // task_page_size,
        },
    }


@router.get(
    "/workspaces/{workspace_id}/observation-batches",
    response_model=OfficialApiObservationBatchListRead,
)
def list_provider_web_search_batches(
    workspace_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    filters = (
        QueueJob.job_type == "geo_observation.batch",
        QueueJob.payload_json["workspace_id"].as_integer() == workspace_id,
    )
    total = int(db.scalar(select(func.count(QueueJob.id)).where(*filters)) or 0)
    batches = list(
        db.scalars(
            select(QueueJob)
            .where(*filters)
            .order_by(QueueJob.created_at.desc(), QueueJob.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return {
        "items": [_official_api_batch_summary(db, batch) for batch in batches],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
        },
    }


@router.get(
    "/workspaces/{workspace_id}/observation-batches/latest",
    response_model=OfficialApiObservationBatchRead,
)
def get_latest_provider_web_search_batch(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return the most recent persisted observation batch for map restoration.

    The decision map is allowed to be revisited without a batch id in the URL.
    Returning the latest batch keeps the last result visible after navigation,
    refresh, or switching desktop spaces; a new run only replaces it once the
    user explicitly submits another measurement.
    """
    workspace_or_404(db, user, workspace_id)
    batch = db.scalar(
        select(QueueJob)
        .where(
            QueueJob.job_type == "geo_observation.batch",
            QueueJob.payload_json["workspace_id"].as_integer() == workspace_id,
        )
        .order_by(QueueJob.created_at.desc(), QueueJob.id.desc())
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="Observation batch not found")
    return _official_api_batch_read(db, batch)


@router.get(
    "/workspaces/{workspace_id}/observation-batches/{batch_id}",
    response_model=OfficialApiObservationBatchRead,
)
def get_provider_web_search_batch(
    workspace_id: int,
    batch_id: int,
    task_page: int = Query(default=1, ge=1),
    task_page_size: int = Query(default=125, ge=1, le=125),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    batch = db.get(QueueJob, batch_id)
    if (
        batch is None
        or batch.job_type != "geo_observation.batch"
        or int((batch.payload_json or {}).get("workspace_id") or 0) != workspace_id
    ):
        raise HTTPException(status_code=404, detail="Observation batch not found")
    return _official_api_batch_read(db, batch, task_page=task_page, task_page_size=task_page_size)


@router.post(
    "/workspaces/{workspace_id}/observations/provider-web-search/queue",
    response_model=QueuedOfficialApiObservationResponse,
    status_code=202,
)
def queue_provider_web_search_observation(
    workspace_id: int,
    payload: OfficialApiObservationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    """Persist a paid provider request and return immediately for worker execution."""

    workspace = workspace_or_404(db, user, workspace_id)
    question = scoped_or_404(db, GeoQuestionPlan, workspace_id, payload.question_plan_id)
    if not _question_sampling_eligible(question):
        raise HTTPException(status_code=409, detail="问题尚未人工批准，不能进入正式采样")
    provider = db.get(LLMProvider, payload.provider_id) if payload.provider_id is not None else None
    if (
        provider is None
        or provider.status != "active"
        or provider.provider_type not in SEARCH_PROVIDER_TYPES
    ):
        raise HTTPException(status_code=422, detail="所选模型未启用，或不具备可审计的联网搜索能力")
    try:
        enforce_monthly_search_budget(db, provider, projected_calls=1)
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    now = datetime.now(timezone.utc)
    model_key = _provider_model_key(provider)
    model_label = _provider_model_label(provider, model_key)
    ledger_batch = GeoObservationBatch(
        workspace_id=workspace_id,
        requested_by_user_id=user.id,
        source_type="official_api_single",
        status="pending",
        provider_count=1,
        question_count=1,
        repeat_count=1,
        total_tasks=1,
        completed_tasks=0,
        failed_tasks=0,
        configuration={
            "schema": "unified-observation-ledger/v1",
            "providers": [{"id": provider.id, "key": model_key, "label": model_label}],
            "questions": [
                {"id": question.id, "key": str(question.id), "label": question.question_text}
            ],
        },
    )
    db.add(ledger_batch)
    db.flush()
    child_payload = {
        "workspace_id": workspace_id,
        # Keep compatibility with the generic queue's project filtering.
        "project_id": workspace_id,
        "company_id": workspace.company_id,
        "actor_user_id": user.id,
        "provider_id": provider.id,
        "provider_key": model_key,
        "provider_label": model_label,
        "question_plan_id": payload.question_plan_id,
        "question_label": question.question_text,
        "repeat_index": payload.repeat_index,
        "repeat_count": payload.repeat_count,
        "observation_group_id": payload.observation_group_id,
        "observation_ledger_batch_id": ledger_batch.id,
    }
    job = QueueJob(
        job_type="geo_observation.collect",
        status="pending",
        priority=10,
        max_attempts=3,
        scheduled_at=now,
        payload_json=child_payload,
    )
    db.add(job)
    db.flush()
    ledger_batch.queue_job_id = job.id
    task = GeoObservationTask(
        batch_id=ledger_batch.id,
        workspace_id=workspace_id,
        queue_job_id=job.id,
        provider_id=provider.id,
        provider_key=provider.provider_type,
        provider_label=model_label,
        model_key=model_key,
        model_label=model_label,
        question_plan_id=question.id,
        question_text_snapshot=question.question_text,
        sample_key=f"provider:{provider.id}:question:{question.id}:repeat:{payload.repeat_index}",
        repeat_index=payload.repeat_index,
        repeat_count=payload.repeat_count,
        observation_group_id=payload.observation_group_id,
        status="pending",
    )
    db.add(task)
    db.flush()
    job.payload_json = {**child_payload, "observation_task_id": task.id}
    db.commit()
    db.refresh(job)
    return {
        "job_id": job.id,
        "status": job.status,
        "message": "观测任务已进入后台队列；页面无需等待模型返回。",
    }


@router.get(
    "/workspaces/{workspace_id}/observation-jobs/{job_id}",
    response_model=OfficialApiObservationJobStatus,
)
def get_provider_web_search_job(
    workspace_id: int,
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    job = db.get(QueueJob, job_id)
    payload_json = dict(job.payload_json or {}) if job is not None else {}
    if (
        job is None
        or job.job_type != "geo_observation.collect"
        or int(payload_json.get("workspace_id") or 0) != workspace_id
    ):
        raise HTTPException(status_code=404, detail="Observation job not found")
    return {
        "job_id": job.id,
        "status": job.status,
        "run_id": payload_json.get("run_id"),
        "evidence_id": payload_json.get("evidence_id"),
        "error_message": job.error_message,
    }


@router.get(
    "/workspaces/{workspace_id}/observation-ledger",
    response_model=ObservationLedgerListRead,
)
def list_observation_ledger(
    workspace_id: int,
    batch_id: int | None = Query(default=None, ge=1),
    model_key: str | None = Query(default=None, min_length=1, max_length=120),
    question_plan_id: int | None = Query(default=None, ge=1),
    status: str | None = Query(default=None, min_length=1, max_length=32),
    source_type: str | None = Query(default=None, min_length=1, max_length=40),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """One query surface for every persisted observation, regardless of adapter."""

    workspace_or_404(db, user, workspace_id)
    filters = [GeoObservationTask.workspace_id == workspace_id]
    if batch_id is not None:
        filters.append(GeoObservationTask.batch_id == batch_id)
    if model_key is not None:
        filters.append(GeoObservationTask.model_key == model_key)
    if question_plan_id is not None:
        filters.append(GeoObservationTask.question_plan_id == question_plan_id)
    if status is not None:
        filters.append(GeoObservationTask.status == status)
    if source_type is not None:
        filters.append(GeoObservationBatch.source_type == source_type)
    base = (
        select(GeoObservationTask, GeoObservationBatch)
        .join(GeoObservationBatch, GeoObservationBatch.id == GeoObservationTask.batch_id)
        .where(*filters)
    )
    total = int(
        db.scalar(
            select(func.count())
            .select_from(GeoObservationTask)
            .join(GeoObservationBatch, GeoObservationBatch.id == GeoObservationTask.batch_id)
            .where(*filters)
        )
        or 0
    )
    rows = db.execute(
        base.order_by(GeoObservationTask.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [
            {
                "task_id": task.id,
                "batch_id": batch.id,
                "source_type": batch.source_type,
                "batch_status": batch.status,
                "task_status": task.status,
                "provider_id": task.provider_id,
                "provider_key": task.provider_key,
                "provider_label": task.provider_label,
                "model_key": task.model_key,
                "model_label": task.model_label,
                "question_plan_id": task.question_plan_id,
                "question_text": task.question_text_snapshot,
                "repeat_index": task.repeat_index,
                "repeat_count": task.repeat_count,
                "run_id": task.run_id,
                "evidence_id": task.evidence_id,
                "queue_job_id": task.queue_job_id,
                "attempt_count": task.attempt_count,
                "error_code": task.error_code,
                "error_detail": task.error_detail,
                "started_at": task.started_at,
                "completed_at": task.completed_at,
                "created_at": task.created_at,
            }
            for task, batch in rows
        ],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
        },
    }


@router.post(
    "/workspaces/{workspace_id}/observations/provider-web-search",
    response_model=OfficialApiObservationResponse,
    status_code=201,
)
@router.post(
    "/workspaces/{workspace_id}/observations/deepseek-official",
    response_model=OfficialApiObservationResponse,
    status_code=201,
    include_in_schema=False,
)
def observe_provider_web_search(
    workspace_id: int,
    payload: OfficialApiObservationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    """Collect one configured provider sample and archive its search evidence.

    The provider adapter requires a final answer and at least one real search
    result.  Failed calls leave a failed run for auditability but never create
    eligible evidence.
    """

    workspace = workspace_or_404(db, user, workspace_id)
    question = scoped_or_404(db, GeoQuestionPlan, workspace_id, payload.question_plan_id)
    if not _question_sampling_eligible(question):
        raise HTTPException(status_code=409, detail="问题尚未人工批准，不能进入正式采样")
    if payload.provider_id is not None:
        provider = db.get(LLMProvider, payload.provider_id)
        if (
            provider is None
            or provider.status != "active"
            or provider.provider_type not in SEARCH_PROVIDER_TYPES
        ):
            raise HTTPException(
                status_code=422, detail="所选模型未启用，或不具备可审计的联网搜索能力"
            )
    else:
        provider = db.scalar(
            select(LLMProvider)
            .where(
                LLMProvider.provider_type == "deepseek_web_search", LLMProvider.status == "active"
            )
            .order_by(LLMProvider.id.desc())
        )
    if provider is None:
        raise HTTPException(status_code=422, detail="请先在运营设置中配置并测试一个联网模型")
    try:
        budget = enforce_monthly_search_budget(db, provider, projected_calls=1)
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    model_key = _provider_model_key(provider)
    model_label = _provider_model_label(provider, model_key)
    prompt_text = question.question_text

    # Worker executions pass the already-created task through SQLAlchemy's
    # session-local context. Direct API calls create their own one-cell batch,
    # so every observation has a durable ledger record before network I/O.
    observation_task_id = int(db.info.get("geo_observation_task_id") or 0)
    observation_task = (
        db.get(GeoObservationTask, observation_task_id) if observation_task_id else None
    )
    if observation_task is not None and (
        observation_task.workspace_id != workspace_id
        or observation_task.provider_id != provider.id
        or observation_task.question_plan_id != question.id
        or observation_task.repeat_index != payload.repeat_index
    ):
        raise HTTPException(status_code=409, detail="观测任务与模型或问题不匹配")
    if observation_task is None:
        ledger_batch = GeoObservationBatch(
            workspace_id=workspace_id,
            requested_by_user_id=user.id,
            source_type="official_api_direct",
            status="pending",
            provider_count=1,
            question_count=1,
            repeat_count=payload.repeat_count,
            total_tasks=1,
            configuration={
                "schema": "unified-observation-ledger/v1",
                "providers": [{"id": provider.id, "key": model_key, "label": model_label}],
                "questions": [
                    {"id": question.id, "key": str(question.id), "label": question.question_text}
                ],
            },
        )
        db.add(ledger_batch)
        db.flush()
        observation_task = GeoObservationTask(
            batch_id=ledger_batch.id,
            workspace_id=workspace_id,
            provider_id=provider.id,
            provider_key=provider.provider_type,
            provider_label=model_label,
            model_key=model_key,
            model_label=model_label,
            question_plan_id=question.id,
            question_text_snapshot=question.question_text,
            sample_key=(
                f"provider:{provider.id}:question:{question.id}:repeat:{payload.repeat_index}"
            ),
            repeat_index=payload.repeat_index,
            repeat_count=payload.repeat_count,
            observation_group_id=payload.observation_group_id,
            status="pending",
        )
        db.add(observation_task)
        db.flush()
        observation_task_id = observation_task.id

    started_at = datetime.now(timezone.utc)
    run = GeoObservationRun(
        workspace_id=workspace_id,
        adapter_key="provider-web-search/v1",
        status="running",
        request_context={
            "schema": "spring-yuan-official-api-observation/v1",
            "provider_id": provider.id,
            "provider_type": provider.provider_type,
            "model": provider.model_name,
            "question_plan_id": question.id,
            "prompt_version": question.prompt_version,
            "repeat_index": payload.repeat_index,
            "repeat_count": payload.repeat_count,
            "observation_group_id": payload.observation_group_id,
            "transport": "aggregate_responses_api"
            if provider.provider_type == "xiaoma_domestic_web_search"
            else "provider_api",
            "model_key": model_key,
            "search_required": True,
        },
        started_at=started_at,
    )
    db.add(run)
    db.flush()
    observation_task.run_id = run.id
    observation_task.status = "running"
    observation_task.attempt_count = max(1, observation_task.attempt_count)
    observation_task.started_at = observation_task.started_at or started_at
    observation_task.error_code = None
    observation_task.error_detail = None
    _refresh_observation_ledger_batch(db, observation_task.batch_id)
    db.commit()
    db.refresh(run)

    company = db.get(Company, workspace.company_id) or Company(
        name=workspace.brand_name,
        industry="",
        website_url=workspace.website_url,
        brand_aliases=workspace.brand_aliases,
    )
    project = Project(
        company_id=workspace.company_id,
        name=f"{workspace.brand_name} GEO provider observation",
        target_industry=company.industry,
        target_audience="企业采购决策者",
    )
    try:
        answer = get_search_provider(provider).answer(prompt_text, company, project, [])
        if answer.collection_method not in {"official_api_web_search", "aggregate_api_web_search"}:
            raise ValueError("Provider did not return eligible API web-search evidence")
        if not answer.search_verified or answer.search_event_count < 1:
            raise ValueError("Provider response did not pass the Web Search execution gate")
        if not answer.source_items or not answer.raw_provider_payload:
            raise ValueError("Provider response is missing searchable source artifacts")

        captured_at = datetime.now(timezone.utc)
        sample_dir = OFFICIAL_API_ARTIFACT_ROOT / model_key / f"run-{run.id}"
        sample_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = sample_dir / "response.json"
        artifact_payload = {
            "schema_version": "spring-yuan-provider-web-search/v1",
            "run_id": run.id,
            "provider_id": provider.id,
            "provider_type": provider.provider_type,
            "model": provider.model_name,
            "question_plan_id": question.id,
            "question": question.question_text,
            "answer": answer.raw_answer,
            "sources": answer.source_items,
            "search_verification": answer.search_verification,
            "captured_at": captured_at.isoformat(),
            "raw_provider_response": answer.raw_provider_payload,
        }
        temporary_path = artifact_path.with_suffix(".json.tmp")
        temporary_path.write_text(
            json.dumps(artifact_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary_path.replace(artifact_path)
        if not artifact_path.exists() or artifact_path.stat().st_size == 0:
            raise ValueError("Provider raw response archive was not created")

        owned_domains: list[str] = []
        website_host = urlsplit(workspace.website_url or "").hostname
        if website_host:
            owned_domains.append(website_host)
        brand_status, brand_position = analyze_brand_status(
            answer.raw_answer,
            answer.source_items,
            workspace.brand_name,
            workspace.brand_aliases,
            owned_domains,
        )
        answer_hash = sha256(
            f"{run.id}|{question.id}|{answer.raw_answer.strip()}".encode()
        ).hexdigest()
        evidence = GeoEvidence(
            workspace_id=workspace_id,
            run_id=run.id,
            question_plan_id=question.id,
            model_key=model_key,
            model_label=model_label,
            prompt_version=question.prompt_version,
            sample_mode="authorized_api",
            evidence_level="auditable",
            collection_method=answer.collection_method,
            evidence_kind="provider_web_search",
            is_real_provider_evidence=True,
            brand_status=brand_status,
            brand_position=brand_position,
            competitor_positions=[],
            answer_text=answer.raw_answer.strip(),
            answer_hash=answer_hash,
            source_items=answer.source_items,
            sampling_environment={
                "provider_id": provider.id,
                "provider_type": provider.provider_type,
                "model": provider.model_name,
                "thinking_mode": str(provider.cost_rule.get("thinking_type") or "disabled"),
                "reasoning_effort": str(provider.cost_rule.get("reasoning_effort") or "low"),
                "endpoint_family": "responses_api",
                "search_required": True,
                "search_verified": answer.search_verified,
                "search_event_count": answer.search_event_count,
                "search_gate": answer.search_verification.get("gate"),
                "search_source_count": len(answer.source_items),
                "repeat_index": payload.repeat_index,
                "repeat_count": payload.repeat_count,
                "observation_group_id": payload.observation_group_id,
                "prompt_is_exact_question": True,
                "personalization": "none",
                "screenshot_applicable": False,
            },
            raw_artifact_uri=artifact_path.resolve().as_uri(),
            screenshot_uri=None,
            captured_at=captured_at,
        )
        db.add(evidence)
        run.status = "completed"
        run.completed_at = captured_at
        run.request_context = {
            **run.request_context,
            "evidence_protocol": "answer+search_sources+raw_provider_response",
            "search_source_count": len(answer.source_items),
        }
        db.flush()
        observation_task = db.get(GeoObservationTask, observation_task_id)
        if observation_task is not None:
            observation_task.run_id = run.id
            observation_task.evidence_id = evidence.id
            observation_task.status = "completed"
            observation_task.completed_at = captured_at
            observation_task.error_code = None
            observation_task.error_detail = None
            _refresh_observation_ledger_batch(db, observation_task.batch_id)
        record_usage(
            db,
            provider=provider,
            action="crawl.answer",
            prompt_text=prompt_text,
            completion_text=answer.raw_answer,
            company_id=workspace.company_id,
            detail={
                "source": "cleanroom_official_api_observation",
                "run_id": run.id,
                "search_event_count": answer.search_event_count,
                "monthly_budget": budget,
            },
        )
        scorecard = write_scorecard(db, workspace_id, run.id)
        db.commit()
        db.refresh(run)
        db.refresh(evidence)
        db.refresh(scorecard)
        return {
            "run": run,
            "evidence": evidence,
            "scorecard": scorecard,
            "message": f"{model_label} 回答、搜索来源和原始响应已归档。",
        }
    except Exception as exc:
        db.rollback()
        failed_run = db.get(GeoObservationRun, run.id)
        if failed_run is not None:
            failed_run.status = "failed"
            failed_run.completed_at = datetime.now(timezone.utc)
            failed_run.failure_reason = str(exc)[:2000]
            # Failed provider calls still consume a request and must count
            # toward the local safety budget; otherwise a broken endpoint can
            # be retried indefinitely without reducing the remaining allowance.
            record_usage(
                db,
                provider=provider,
                action="crawl.answer",
                prompt_text=prompt_text,
                completion_text="",
                company_id=workspace.company_id,
                detail={
                    "source": "cleanroom_official_api_observation",
                    "run_id": run.id,
                    "ok": False,
                    "error": str(exc)[:800],
                },
            )
            observation_task = db.get(GeoObservationTask, observation_task_id)
            if observation_task is not None:
                observation_task.run_id = run.id
                observation_task.status = "failed"
                observation_task.error_code = type(exc).__name__[:80]
                observation_task.error_detail = str(exc)[:2000]
                observation_task.completed_at = failed_run.completed_at
                _refresh_observation_ledger_batch(db, observation_task.batch_id)
            db.commit()
        raise HTTPException(
            status_code=502, detail=f"模型联网搜索观测失败：{str(exc)[:800]}"
        ) from exc


@router.post(
    "/workspaces/{workspace_id}/imports/yao", response_model=ScorecardRead, status_code=201
)
def import_yao_dataset(
    workspace_id: int,
    payload: YaoDatasetImport,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
    target_run_id: int | None = None,
):
    workspace_or_404(db, user, workspace_id)
    db.flush()
    if target_run_id is None:
        run = GeoObservationRun(
            workspace_id=workspace_id,
            adapter_key=f"yao-{payload.platform}",
            status="running",
            request_context={
                "schema": "yao-compatible/v1",
                "sample_mode": payload.sample_mode,
                "sample_count": len(payload.samples),
            },
            started_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.flush()
        allowed_plan_ids: set[int] | None = None
    else:
        run = scoped_or_404(db, GeoObservationRun, workspace_id, target_run_id)
        if run.adapter_key != "standard-observation-plan/v1":
            raise HTTPException(
                status_code=422,
                detail="Only a standard observation run can receive live crawler samples",
            )
        if run.status not in {"queued", "running", "partial"}:
            raise HTTPException(status_code=409, detail="This observation run is already closed")
        allowed_plan_ids = set(run.request_context.get("question_plan_ids", []))
        run.status = "running"
        run.started_at = run.started_at or datetime.now(timezone.utc)
    browser_account = _account_for_import(db, workspace_id, payload, target_run_id)
    account_provenance = (
        {
            "browser_account_id": browser_account.id,
            "browser_account_alias": browser_account.alias,
            "browser_account_cohort": browser_account.cohort,
        }
        if browser_account is not None
        else {}
    )
    repeat_count = max((sample.repeat_index for sample in payload.samples), default=1)
    ledger_batch = GeoObservationBatch(
        workspace_id=workspace_id,
        requested_by_user_id=user.id,
        source_type=f"yao_{payload.platform}",
        status="pending",
        provider_count=1,
        question_count=len({sample.question for sample in payload.samples}),
        repeat_count=repeat_count,
        total_tasks=len(payload.samples),
        configuration={
            "schema": "unified-observation-ledger/v1",
            "import_schema": "yao-compatible/v1",
            "platform": payload.platform,
            "sample_mode": payload.sample_mode,
            "target_run_id": target_run_id,
        },
        started_at=datetime.now(timezone.utc),
    )
    db.add(ledger_batch)
    db.flush()
    for sample in payload.samples:
        plan = db.scalar(
            select(GeoQuestionPlan).where(
                GeoQuestionPlan.workspace_id == workspace_id,
                GeoQuestionPlan.question_text == sample.question,
            )
        )
        if plan is None:
            if allowed_plan_ids is not None:
                raise HTTPException(
                    status_code=422,
                    detail="Sample question is not in the standard observation plan",
                )
            plan = GeoQuestionPlan(
                workspace_id=workspace_id,
                question_text=sample.question,
                importance=3,
                is_brand_query=False,
            )
            db.add(plan)
            db.flush()
        elif allowed_plan_ids is not None and plan.id not in allowed_plan_ids:
            raise HTTPException(
                status_code=422, detail="Sample question is not in the standard observation plan"
            )
        raw = sample.answer_text.strip()
        has_audit_artifact = bool(sample.raw_artifact_uri or sample.screenshot_uri)
        real = bool(
            sample.ok
            and raw
            and has_audit_artifact
            and payload.evidence_level == "auditable"
            and payload.sample_mode in {"browser_assisted", "authorized_api"}
        )
        answer_hash = sha256(f"{run.id}|{sample.sample_id}|{raw}".encode()).hexdigest()
        evidence = GeoEvidence(
                workspace_id=workspace_id,
                run_id=run.id,
                question_plan_id=plan.id,
                model_key=payload.platform,
                model_label=MODEL_LABELS[payload.platform],
                prompt_version=payload.prompt_version,
                sample_mode=payload.sample_mode,
                evidence_level=payload.evidence_level,
                collection_method="web_ui"
                if payload.sample_mode == "browser_assisted"
                else payload.sample_mode,
                evidence_kind="yao_import",
                is_real_provider_evidence=real,
                brand_status=sample.brand_status,
                brand_position=sample.brand_position,
                competitor_positions=sample.competitor_positions,
                answer_text=raw or "[capture failed]",
                answer_hash=answer_hash,
                source_items=[item.model_dump() for item in sample.references],
                sampling_environment={
                    **sample.sampling_environment,
                    **account_provenance,
                    "repeat_index": sample.repeat_index,
                    "sample_id": sample.sample_id,
                },
                raw_artifact_uri=sample.raw_artifact_uri,
                screenshot_uri=sample.screenshot_uri,
                captured_at=sample.finished_at or sample.started_at or datetime.now(timezone.utc),
            )
        db.add(evidence)
        db.flush()
        sample_completed = bool(sample.ok and raw)
        completed_at = sample.finished_at or sample.started_at or datetime.now(timezone.utc)
        db.add(
            GeoObservationTask(
                batch_id=ledger_batch.id,
                workspace_id=workspace_id,
                run_id=run.id,
                evidence_id=evidence.id,
                provider_key=f"yao_{payload.platform}",
                provider_label=f"{MODEL_LABELS[payload.platform]} · Yao 导入",
                model_key=payload.platform,
                model_label=MODEL_LABELS[payload.platform],
                question_plan_id=plan.id,
                question_text_snapshot=plan.question_text,
                sample_key=f"yao-sample:{sample.sample_id}",
                repeat_index=sample.repeat_index,
                repeat_count=repeat_count,
                status="completed" if sample_completed else "failed",
                attempt_count=1,
                error_code=None if sample_completed else "capture_failed",
                error_detail=None if sample_completed else "Yao 样本未返回有效回答",
                started_at=sample.started_at or completed_at,
                completed_at=completed_at,
            )
        )
    if target_run_id is None:
        run.status = "completed"
        run.completed_at = datetime.now(timezone.utc)
    else:
        expected = (
            len(allowed_plan_ids or [])
            * len(STANDARD_MODELS)
            * int(run.request_context.get("repeat_count", 1))
        )
        collected = len(
            list(
                db.scalars(
                    select(GeoEvidence).where(
                        GeoEvidence.workspace_id == workspace_id, GeoEvidence.run_id == run.id
                    )
                )
            )
        )
        run.status = "completed" if collected >= expected else "partial"
        run.completed_at = datetime.now(timezone.utc) if run.status == "completed" else None
        run.request_context = {
            **run.request_context,
            "last_ingest": {
                "platform": payload.platform,
                "sample_count": len(payload.samples),
                "at": datetime.now(timezone.utc).isoformat(),
            },
        }
    db.flush()
    _refresh_observation_ledger_batch(db, ledger_batch.id)
    scorecard = write_scorecard(db, workspace_id, run.id)
    if browser_account is not None:
        browser_account.status = "ready"
        browser_account.consecutive_failures = 0
        browser_account.cooldown_until = None
        browser_account.last_checked_at = datetime.now(timezone.utc)
        browser_account.health_note = "采样已归档，可继续使用"
        _clear_lease(browser_account)
    db.commit()
    db.refresh(scorecard)
    return scorecard


@router.post(
    "/workspaces/{workspace_id}/imports/yao/deepseek-stage1",
    response_model=ScorecardRead,
    status_code=201,
)
def import_yao_deepseek_stage1(
    workspace_id: int,
    payload: YaoDeepSeekDatasetImport,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace = workspace_or_404(db, user, workspace_id)
    normalized = normalize_yao_stage1_dataset(
        workspace, payload, "deepseek", "yao-deepseek-crawler/"
    )
    return import_yao_dataset(workspace_id, normalized, db, user, payload.target_run_id)


@router.post(
    "/workspaces/{workspace_id}/imports/yao/doubao-stage1",
    response_model=ScorecardRead,
    status_code=201,
)
def import_yao_doubao_stage1(
    workspace_id: int,
    payload: YaoDoubaoDatasetImport,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace = workspace_or_404(db, user, workspace_id)
    normalized = normalize_yao_stage1_dataset(workspace, payload, "doubao", "yao-doubao-crawler/")
    return import_yao_dataset(workspace_id, normalized, db, user, payload.target_run_id)


@router.get("/workspaces/{workspace_id}/evidence", response_model=list[EvidenceRead])
def list_evidence(
    workspace_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    workspace_or_404(db, user, workspace_id)
    return list(
        db.scalars(
            select(GeoEvidence)
            .where(GeoEvidence.workspace_id == workspace_id)
            .order_by(GeoEvidence.captured_at.desc(), GeoEvidence.id.desc())
        )
    )


@router.get(
    "/workspaces/{workspace_id}/evidence/action-summary",
    response_model=list[ActionEvidenceSummaryRead],
)
def list_action_evidence_summary(
    workspace_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Return only the evidence fields required by the priority-action fallback."""
    workspace_or_404(db, user, workspace_id)
    rows = db.execute(
        select(
            GeoEvidence.id,
            GeoEvidence.question_plan_id,
            GeoEvidence.model_label,
            GeoEvidence.is_real_provider_evidence,
            GeoEvidence.brand_status,
            GeoEvidence.competitor_positions,
            GeoEvidence.source_items,
        )
        .where(GeoEvidence.workspace_id == workspace_id)
        .order_by(GeoEvidence.captured_at.desc(), GeoEvidence.id.desc())
    ).all()
    return [
        {
            "id": row.id,
            "question_plan_id": row.question_plan_id,
            "model_label": row.model_label,
            "is_real_provider_evidence": row.is_real_provider_evidence,
            "brand_status": row.brand_status,
            "competitor_positions": row.competitor_positions or [],
            "source_items": row.source_items or [],
        }
        for row in rows
    ]


@router.get(
    "/workspaces/{workspace_id}/question-plans/{question_id}/analysis",
    response_model=QuestionAnalysisRead,
)
def get_question_analysis(
    workspace_id: int,
    question_id: int,
    scope: str = Query(default="current", pattern=r"^(current|7|30|90)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return the evidence-backed analysis for one library question.

    This endpoint is intentionally read-only and computes from archived real
    evidence. Selecting a question never triggers a provider call.
    """
    workspace = workspace_or_404(db, user, workspace_id)
    question = scoped_or_404(db, GeoQuestionPlan, workspace_id, question_id)
    rows = list(
        db.scalars(
            select(GeoEvidence)
            .where(
                GeoEvidence.workspace_id == workspace_id,
                GeoEvidence.question_plan_id == question_id,
                GeoEvidence.is_real_provider_evidence.is_(True),
            )
            .order_by(GeoEvidence.captured_at.desc(), GeoEvidence.id.desc())
        )
    )
    period_days = None if scope == "current" else int(scope)
    return build_question_analysis(
        workspace,
        question,
        rows,
        scope=scope,
        period_days=period_days,
    )


@router.get("/workspaces/{workspace_id}/scorecards/latest", response_model=ScorecardRead | None)
def latest_scorecard(
    workspace_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    workspace_or_404(db, user, workspace_id)
    return db.scalar(
        select(GeoScorecard)
        .where(GeoScorecard.workspace_id == workspace_id)
        .order_by(GeoScorecard.id.desc())
    )


@router.get("/workspaces/{workspace_id}/source-map", response_model=SourceMapRead)
def get_source_map(
    workspace_id: int,
    period_days: int | None = Query(default=30, ge=1, le=3650),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    model_key: str | None = Query(default=None, min_length=1, max_length=120),
    question_plan_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=12, ge=1, le=50),
    evidence_limit: int = Query(default=12, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace = workspace_or_404(db, user, workspace_id)
    if question_plan_id is not None:
        scoped_or_404(db, GeoQuestionPlan, workspace_id, question_plan_id)

    effective_to = date_to or datetime.now(timezone.utc)
    effective_from = date_from
    if effective_to.tzinfo is None:
        effective_to = effective_to.replace(tzinfo=timezone.utc)
    if effective_from is not None and effective_from.tzinfo is None:
        effective_from = effective_from.replace(tzinfo=timezone.utc)
    if effective_from is None and period_days is not None:
        effective_from = effective_to - timedelta(days=period_days)
    if effective_from is not None and effective_from > effective_to:
        raise HTTPException(status_code=422, detail="date_from must be before date_to")

    scoped_query = select(GeoEvidence).where(GeoEvidence.workspace_id == workspace_id)
    if effective_from is not None:
        scoped_query = scoped_query.where(GeoEvidence.captured_at >= effective_from)
    if effective_to is not None:
        scoped_query = scoped_query.where(GeoEvidence.captured_at <= effective_to)
    if model_key:
        scoped_query = scoped_query.where(GeoEvidence.model_key == model_key.strip())
    if question_plan_id is not None:
        scoped_query = scoped_query.where(GeoEvidence.question_plan_id == question_plan_id)
    scoped_rows = list(
        db.scalars(scoped_query.order_by(GeoEvidence.captured_at.desc(), GeoEvidence.id.desc()))
    )
    real_rows = [row for row in scoped_rows if row.is_real_provider_evidence]
    questions = list(
        db.scalars(
            select(GeoQuestionPlan)
            .where(GeoQuestionPlan.workspace_id == workspace_id, GeoQuestionPlan.active.is_(True))
            .order_by(GeoQuestionPlan.importance.desc(), GeoQuestionPlan.id)
        )
    )
    aggregates = build_source_map(
        real_rows,
        questions,
        limit=limit,
        evidence_limit=evidence_limit,
        excluded_non_real_answer_count=len(scoped_rows) - len(real_rows),
    )
    available_models = dict(
        db.execute(
            select(GeoEvidence.model_key, GeoEvidence.model_label)
            .where(
                GeoEvidence.workspace_id == workspace_id,
                GeoEvidence.is_real_provider_evidence.is_(True),
            )
            .distinct()
            .order_by(GeoEvidence.model_label, GeoEvidence.model_key)
        ).all()
    )
    return {
        "workspace": workspace,
        "scope": {
            "date_from": effective_from,
            "date_to": effective_to,
            "period_days": period_days if date_from is None else None,
            "model_key": model_key.strip() if model_key else None,
            "question_plan_id": question_plan_id,
            "real_provider_evidence_only": True,
        },
        **aggregates,
        "available_models": [
            {"key": key, "label": label} for key, label in available_models.items()
        ],
        "available_questions": questions,
        "interpretation_notice": (
            "本页只说明某 URL 出现在已归档回答的引用中。品牌未出现仅指回答文本的"
            "识别结果；未抓取并核验网页正文前，不能据此判断网页是否提及品牌。"
        ),
    }


@router.get(
    "/workspaces/{workspace_id}/competitor-comparison",
    response_model=CompetitorComparisonRead,
)
def get_competitor_comparison(
    workspace_id: int,
    period_days: int | None = Query(default=30, ge=1, le=3650),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    model_key: str | None = Query(default=None, min_length=1, max_length=120),
    question_plan_id: int | None = Query(default=None, ge=1),
    evidence_limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace = workspace_or_404(db, user, workspace_id)
    if question_plan_id is not None:
        scoped_or_404(db, GeoQuestionPlan, workspace_id, question_plan_id)

    effective_to = date_to or datetime.now(timezone.utc)
    effective_from = date_from
    if effective_to.tzinfo is None:
        effective_to = effective_to.replace(tzinfo=timezone.utc)
    if effective_from is not None and effective_from.tzinfo is None:
        effective_from = effective_from.replace(tzinfo=timezone.utc)
    if effective_from is None and period_days is not None:
        effective_from = effective_to - timedelta(days=period_days)
    if effective_from is not None and effective_from > effective_to:
        raise HTTPException(status_code=422, detail="date_from must be before date_to")

    scoped_query = select(GeoEvidence).where(GeoEvidence.workspace_id == workspace_id)
    if effective_from is not None:
        scoped_query = scoped_query.where(GeoEvidence.captured_at >= effective_from)
    if effective_to is not None:
        scoped_query = scoped_query.where(GeoEvidence.captured_at <= effective_to)
    if model_key:
        scoped_query = scoped_query.where(GeoEvidence.model_key == model_key.strip())
    if question_plan_id is not None:
        scoped_query = scoped_query.where(GeoEvidence.question_plan_id == question_plan_id)
    scoped_rows = list(
        db.scalars(scoped_query.order_by(GeoEvidence.captured_at.desc(), GeoEvidence.id.desc()))
    )
    real_rows = [row for row in scoped_rows if row.is_real_provider_evidence]
    questions = list(
        db.scalars(
            select(GeoQuestionPlan)
            .where(
                GeoQuestionPlan.workspace_id == workspace_id,
                GeoQuestionPlan.active.is_(True),
            )
            .order_by(GeoQuestionPlan.importance.desc(), GeoQuestionPlan.id)
        )
    )
    comparison = build_competitor_comparison(
        workspace,
        real_rows,
        questions,
        excluded_non_real_answer_count=len(scoped_rows) - len(real_rows),
        evidence_limit=evidence_limit,
    )
    available_models = dict(
        db.execute(
            select(GeoEvidence.model_key, GeoEvidence.model_label)
            .where(
                GeoEvidence.workspace_id == workspace_id,
                GeoEvidence.is_real_provider_evidence.is_(True),
            )
            .distinct()
            .order_by(GeoEvidence.model_label, GeoEvidence.model_key)
        ).all()
    )
    return {
        "workspace": workspace,
        "scope": {
            "date_from": effective_from,
            "date_to": effective_to,
            "period_days": period_days if date_from is None else None,
            "model_key": model_key.strip() if model_key else None,
            "question_plan_id": question_plan_id,
            "real_provider_evidence_only": True,
        },
        **comparison,
        "available_models": [
            {"key": key, "label": label} for key, label in available_models.items()
        ],
        "available_questions": questions,
    }


@router.post(
    "/workspaces/{workspace_id}/competitor-insights",
    response_model=CompetitorInsightRead,
)
def generate_workspace_competitor_insight(
    workspace_id: int,
    payload: CompetitorInsightRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Generate an on-demand DeepSeek insight from the exact selected scope.

    This is intentionally not an observation and writes nothing to the
    workspace. The client receives a transient, evidence-referenced analysis.
    """
    workspace = workspace_or_404(db, user, workspace_id)
    selected_question = None
    if payload.question_plan_id is not None:
        selected_question = scoped_or_404(
            db, GeoQuestionPlan, workspace_id, payload.question_plan_id
        )
    effective_to = datetime.now(timezone.utc)
    effective_from = effective_to - timedelta(days=payload.period_days)
    scoped_query = select(GeoEvidence).where(
        GeoEvidence.workspace_id == workspace_id,
        GeoEvidence.captured_at >= effective_from,
        GeoEvidence.captured_at <= effective_to,
    )
    model_key = (payload.model_key or "").strip()
    if model_key and model_key != "all":
        scoped_query = scoped_query.where(GeoEvidence.model_key == model_key)
    else:
        model_key = ""
    if payload.question_plan_id is not None:
        scoped_query = scoped_query.where(GeoEvidence.question_plan_id == payload.question_plan_id)
    scoped_rows = list(
        db.scalars(scoped_query.order_by(GeoEvidence.captured_at.desc(), GeoEvidence.id.desc()))
    )
    real_rows = [row for row in scoped_rows if row.is_real_provider_evidence]
    questions = list(
        db.scalars(
            select(GeoQuestionPlan)
            .where(GeoQuestionPlan.workspace_id == workspace_id, GeoQuestionPlan.active.is_(True))
            .order_by(GeoQuestionPlan.importance.desc(), GeoQuestionPlan.id)
        )
    )
    comparison = build_competitor_comparison(
        workspace,
        real_rows,
        questions,
        excluded_non_real_answer_count=len(scoped_rows) - len(real_rows),
        evidence_limit=payload.evidence_limit,
    )
    model_label = "全部已测模型"
    if model_key:
        model_label = next(
            (row.model_label for row in real_rows if row.model_key == model_key), model_key
        )
    question_label = (
        selected_question.question_text if selected_question is not None else "全部已选问题"
    )
    try:
        return generate_competitor_insight(
            comparison,
            api_key=get_settings().deepseek_api_key,
            selected_question_id=payload.question_plan_id,
            selected_question_label=question_label,
            selected_model_label=model_label,
            selected_period_label=("全部归档" if payload.period_days == 3650 else f"近 {payload.period_days} 天"),
        )
    except CompetitorInsightError as error:
        status_code = 503 if "API Key" in str(error) else 502
        raise HTTPException(status_code=status_code, detail=str(error)) from error


@router.get("/workspaces/{workspace_id}/decision-map", response_model=DecisionMapRead)
def get_decision_map(
    workspace_id: int,
    period_days: int = Query(30, ge=1, le=3650),
    model_key: str | None = Query(default=None, min_length=1, max_length=40),
    scope: str = Query("high", pattern=r"^(all|high)$"),
    batch_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # FastAPI supplies concrete values at runtime; the guard also keeps direct
    # service-level calls (used by the local verification scripts) predictable.
    if not isinstance(period_days, int):
        period_days = 30
    if not isinstance(scope, str) or scope not in {"all", "high"}:
        scope = "high"
    if not isinstance(model_key, str) or not model_key.strip():
        model_key = None
    workspace = workspace_or_404(db, user, workspace_id)
    questions = list(
        db.scalars(
            select(GeoQuestionPlan)
            .where(
                GeoQuestionPlan.workspace_id == workspace_id,
                GeoQuestionPlan.active.is_(True),
                GeoQuestionPlan.status.in_(("approved", "active")),
            )
            .order_by(GeoQuestionPlan.importance.desc(), GeoQuestionPlan.id)
        )
    )
    all_evidence_rows = list(
        db.scalars(
            select(GeoEvidence)
            .where(GeoEvidence.workspace_id == workspace_id)
            .order_by(GeoEvidence.captured_at.desc(), GeoEvidence.id.desc())
        )
    )
    measurement_batch: QueueJob | None = None
    measurement_evidence_ids: set[int] | None = None
    if batch_id is not None:
        measurement_batch = db.get(QueueJob, batch_id)
        if (
            measurement_batch is None
            or measurement_batch.job_type != "geo_observation.batch"
            or int((measurement_batch.payload_json or {}).get("workspace_id") or 0) != workspace_id
        ):
            raise HTTPException(status_code=404, detail="Observation batch not found")
        child_ids = [
            int(value)
            for value in (measurement_batch.payload_json or {}).get("child_job_ids") or []
        ]
        children = (
            list(db.scalars(select(QueueJob).where(QueueJob.id.in_(child_ids))))
            if child_ids
            else []
        )
        measurement_evidence_ids = {
            int(value)
            for child in children
            for value in [(child.payload_json or {}).get("evidence_id")]
            if value is not None
        }
    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)

    # The map is an operational view of the current official collection path.
    # Historical web-ui/aggregate imports remain available in Evidence, but
    # must not silently change current KPI cells or mix transport methods.
    def is_recent(captured_at: datetime | None) -> bool:
        if captured_at is None:
            return False
        normalized = (
            captured_at.replace(tzinfo=timezone.utc) if captured_at.tzinfo is None else captured_at
        )
        return normalized >= cutoff

    evidence_rows = [
        evidence
        for evidence in all_evidence_rows
        if evidence.collection_method == "official_api_web_search"
        and evidence.is_real_provider_evidence
        and (measurement_evidence_ids is None or evidence.id in measurement_evidence_ids)
        and is_recent(evidence.captured_at)
        and (model_key is None or evidence.model_key == model_key)
    ]
    if scope == "high":
        high_importance = {plan.id for plan in questions if plan.importance >= 4}
        evidence_rows = [
            evidence for evidence in evidence_rows if evidence.question_plan_id in high_importance
        ]
    latest_by_cell: dict[tuple[int, str], GeoEvidence] = {}
    for evidence in evidence_rows:
        latest_by_cell.setdefault((evidence.question_plan_id, evidence.model_key), evidence)
    # V1 has one stable decision-map column per supported official platform.
    # Historic/experimental providers remain in the evidence archive, but must
    # not add columns or rename the product surface (for example "聚合 API").
    models = [{"key": key, "label": label} for key, label in STANDARD_MODELS]
    cells = [
        {
            "question_plan_id": plan.id,
            "model_key": model["key"],
            "model_label": model["label"],
            "evidence": latest_by_cell.get((plan.id, model["key"])),
        }
        for plan in questions
        for model in models
    ]
    # KPI wording says "natural" visibility, so branded prompts must never be
    # counted in either the numerator or denominator. Keep them in the evidence
    # archive/map if needed, but calculate KPI ratios only from non-brand prompts.
    non_brand_question_ids = {plan.id for plan in questions if not plan.is_brand_query}
    metric_evidence_rows = [
        evidence
        for evidence in evidence_rows
        if evidence.question_plan_id in non_brand_question_ids
    ]
    scoped_metrics, metric_explanation, _ = score_evidence(metric_evidence_rows)
    scorecard = db.scalar(
        select(GeoScorecard)
        .where(GeoScorecard.workspace_id == workspace_id)
        .order_by(GeoScorecard.id.desc())
    )
    return {
        "workspace": workspace,
        "questions": questions,
        "scorecard": scorecard,
        "models": models,
        "cells": cells,
        "metrics": scoped_metrics,
        "metric_scope": {
            "period_days": period_days,
            "batch_id": measurement_batch.id if measurement_batch else None,
            "batch_created_at": measurement_batch.created_at if measurement_batch else None,
            "batch_finished_at": measurement_batch.finished_at if measurement_batch else None,
            "measurement_basis": "single_batch" if measurement_batch else "historical_period",
            "model_key": model_key,
            "scope": scope,
            "collection_method": "official_api_web_search",
            "last_observed_at": metric_evidence_rows[0].captured_at
            if metric_evidence_rows
            else None,
            "scoring_version": SCORING_VERSION,
            "eligibility": metric_explanation["eligibility"],
            "brand_query_policy": "excluded",
        },
        "sample_count": len(metric_evidence_rows),
    }


def _opportunity_read(db: Session, opportunity: GeoActionOpportunity) -> dict:
    evidence = list(
        db.scalars(
            select(GeoActionOpportunityEvidence)
            .where(GeoActionOpportunityEvidence.opportunity_id == opportunity.id)
            .order_by(GeoActionOpportunityEvidence.id.asc())
        )
    )
    return {"id": opportunity.id, "evidence": evidence, **opportunity.__dict__}


@router.post(
    "/workspaces/{workspace_id}/action-opportunities/discover",
    response_model=list[ActionOpportunityRead],
)
def discover_action_opportunities(
    workspace_id: int,
    payload: ActionOpportunityDiscoverRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace = workspace_or_404(db, user, workspace_id)
    effective_batch_id = payload.batch_id or db.scalar(
        select(GeoObservationBatch.id)
        .where(
            GeoObservationBatch.workspace_id == workspace_id,
            GeoObservationBatch.status.in_(["completed", "succeeded"]),
        )
        .order_by(GeoObservationBatch.id.desc())
        .limit(1)
    )
    if effective_batch_id:
        batch = scoped_or_404(db, GeoObservationBatch, workspace_id, effective_batch_id)
        if batch.status not in {"completed", "succeeded"}:
            raise HTTPException(
                status_code=422,
                detail="Only a completed observation batch can produce priority opportunities",
            )
    if payload.question_plan_ids:
        for question_id in payload.question_plan_ids:
            scoped_or_404(db, GeoQuestionPlan, workspace_id, question_id)
    opportunities = discover_opportunities(
        db,
        workspace,
        batch_id=effective_batch_id,
        question_plan_ids=payload.question_plan_ids or None,
        max_items=payload.max_items,
    )
    db.add(
        GeoActionEvent(
            workspace_id=workspace_id,
            event_type="opportunities_discovered",
            actor_type="user",
            actor_user_id=user.id,
            detail={
                "batch_id": effective_batch_id,
                "opportunity_count": len(opportunities),
                "evidence_gate": "real_answer+source_url+raw_artifact+completed_task",
            },
        )
    )
    db.commit()
    return [_opportunity_read(db, opportunity) for opportunity in opportunities]


@router.get(
    "/workspaces/{workspace_id}/action-opportunities",
    response_model=list[ActionOpportunityRead],
)
def list_action_opportunities(
    workspace_id: int,
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    query = select(GeoActionOpportunity).where(GeoActionOpportunity.workspace_id == workspace_id)
    if status:
        query = query.where(GeoActionOpportunity.status == status)
    else:
        query = query.where(GeoActionOpportunity.status.in_(["open", "selected"]))
    rows = list(db.scalars(query.order_by(GeoActionOpportunity.priority_score.desc(), GeoActionOpportunity.id.desc())))
    return [_opportunity_read(db, opportunity) for opportunity in rows]


@router.post(
    "/workspaces/{workspace_id}/action-opportunities/{opportunity_id}/select",
    response_model=ActionRead,
    status_code=201,
)
def select_action_opportunity(
    workspace_id: int,
    opportunity_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    opportunity = scoped_or_404(db, GeoActionOpportunity, workspace_id, opportunity_id)
    if opportunity.status in {"selected", "completed", "dismissed"}:
        raise HTTPException(status_code=409, detail="Opportunity is no longer selectable")
    existing = db.scalar(
        select(GeoOptimizationAction).where(GeoOptimizationAction.opportunity_id == opportunity.id)
    )
    if existing:
        raise HTTPException(status_code=409, detail="Opportunity already has an action")
    links = list(
        db.scalars(
            select(GeoActionOpportunityEvidence)
            .where(GeoActionOpportunityEvidence.opportunity_id == opportunity.id)
            .order_by(GeoActionOpportunityEvidence.id.asc())
        )
    )
    question_plan_id = opportunity.scope_snapshot.get("question_plan_id")
    action = GeoOptimizationAction(
        workspace_id=workspace_id,
        opportunity_id=opportunity.id,
        question_plan_id=question_plan_id,
        source_evidence_id=links[0].evidence_id if links else None,
        title=opportunity.title,
        rationale=opportunity.summary,
        hypothesis="补齐可引用、可复测的品牌答案后，目标问题中的品牌出现率应提升。",
        priority=opportunity.priority_label,
        status="proposed",
        stage="selected",
        baseline_snapshot=opportunity.scope_snapshot,
        selected_scope={
            "opportunity_id": opportunity.id,
            "evidence_ids": [link.evidence_id for link in links],
            "question_plan_id": question_plan_id,
        },
        selected_at=datetime.now(timezone.utc),
    )
    opportunity.status = "selected"
    db.add(action)
    db.flush()
    db.add(
        GeoActionEvent(
            workspace_id=workspace_id,
            action_id=action.id,
            event_type="opportunity_selected",
            from_stage=None,
            to_stage="selected",
            actor_type="user",
            actor_user_id=user.id,
            detail={"opportunity_id": opportunity.id, "evidence_ids": action.selected_scope["evidence_ids"]},
        )
    )
    db.commit()
    db.refresh(action)
    return action


@router.post("/workspaces/{workspace_id}/actions", response_model=ActionRead, status_code=201)
def create_action(
    workspace_id: int,
    payload: ActionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    if payload.question_plan_id:
        scoped_or_404(db, GeoQuestionPlan, workspace_id, payload.question_plan_id)
    if payload.source_evidence_id:
        scoped_or_404(db, GeoEvidence, workspace_id, payload.source_evidence_id)
    action = GeoOptimizationAction(workspace_id=workspace_id, **payload.model_dump())
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


@router.post(
    "/workspaces/{workspace_id}/actions/{action_id}/stage",
    response_model=ActionRead,
)
def update_action_stage(
    workspace_id: int,
    action_id: int,
    payload: ActionStageUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    action = scoped_or_404(db, GeoOptimizationAction, workspace_id, action_id)
    if payload.stage == "closed" and not db.scalar(
        select(GeoReobservation).where(GeoReobservation.action_id == action.id)
    ):
        raise HTTPException(status_code=422, detail="A re-observation is required before closing an action")
    previous = action.stage
    action.stage = payload.stage
    if payload.stage in {"brief_ready", "generating", "draft_ready", "reviewing", "sync_requested", "awaiting_readback", "blocked"}:
        action.status = "in_progress"
    elif payload.stage == "verified":
        action.status = "verified"
    elif payload.stage == "closed":
        action.status = "closed"
        action.completed_at = datetime.now(timezone.utc)
    db.add(
        GeoActionEvent(
            workspace_id=workspace_id,
            action_id=action.id,
            event_type="stage_changed",
            from_stage=previous,
            to_stage=payload.stage,
            actor_type="user",
            actor_user_id=user.id,
            detail={"note": payload.note} if payload.note else {},
        )
    )
    db.commit()
    db.refresh(action)
    return action


@router.get(
    "/workspaces/{workspace_id}/actions/{action_id}/events",
    response_model=list[ActionEventRead],
)
def list_action_events(
    workspace_id: int,
    action_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    scoped_or_404(db, GeoOptimizationAction, workspace_id, action_id)
    return list(
        db.scalars(
            select(GeoActionEvent)
            .where(GeoActionEvent.workspace_id == workspace_id, GeoActionEvent.action_id == action_id)
            .order_by(GeoActionEvent.id.asc())
        )
    )


@router.post(
    "/workspaces/{workspace_id}/actions/{action_id}/briefs",
    response_model=ContentBriefRead,
    status_code=201,
)
def create_content_brief(
    workspace_id: int,
    action_id: int,
    payload: ContentBriefCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    action = scoped_or_404(db, GeoOptimizationAction, workspace_id, action_id)
    question = db.get(GeoQuestionPlan, action.question_plan_id) if action.question_plan_id else None
    links = []
    if action.opportunity_id:
        links = list(
            db.scalars(
                select(GeoActionOpportunityEvidence)
                .where(GeoActionOpportunityEvidence.opportunity_id == action.opportunity_id)
                .order_by(GeoActionOpportunityEvidence.id.asc())
            )
        )
    if action.source_evidence_id and not any(link.evidence_id == action.source_evidence_id for link in links):
        evidence = scoped_or_404(db, GeoEvidence, workspace_id, action.source_evidence_id)
        links.append(
            GeoActionOpportunityEvidence(
                evidence_id=evidence.id,
                question_plan_id=evidence.question_plan_id,
                model_key=evidence.model_key,
                signal_type="action_source",
                signal_value={},
                evidence_hash=evidence.answer_hash,
                source_url=next((_source.get("url") for _source in (evidence.source_items or []) if isinstance(_source, dict) and str(_source.get("url", "")).startswith(("http://", "https://"))), None),
            )
        )
    evidence_ids = [link.evidence_id for link in links if getattr(link, "evidence_id", None)]
    source_urls = list(dict.fromkeys(link.source_url for link in links if getattr(link, "source_url", None)))
    audience = payload.audience or ({"ciso": "安全与技术决策者", "procurement": "采购与业务负责人"}.get(question.role, "技术负责人") if question else "技术负责人")
    intent = payload.intent or (question.journey_stage if question else "consideration")
    required_sections = payload.required_sections or ["问题背景", "可验证的解决方案", "证据与引用", "下一步行动"]
    required_claims = [f"直接回答问题：{question.question_text}"] if question else [action.title]
    required_claims.append(f"所有关键事实均需引用已采集来源（{len(source_urls)} 个）")
    input_fingerprint = sha256(
        json.dumps(
            {"action_id": action.id, "audience": audience, "intent": intent, "sections": required_sections, "evidence_ids": evidence_ids, "source_urls": source_urls},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    existing = db.scalar(
        select(GeoContentBrief).where(
            GeoContentBrief.workspace_id == workspace_id,
            GeoContentBrief.input_fingerprint == input_fingerprint,
        )
    )
    if existing:
        return existing
    brief = GeoContentBrief(
        workspace_id=workspace_id,
        action_id=action.id,
        question_plan_id=question.id if question else None,
        audience=audience,
        intent=intent,
        asset_type=payload.asset_type,
        required_sections=required_sections,
        brand_fact_ids=payload.brand_fact_ids,
        evidence_ids=evidence_ids,
        source_urls=source_urls,
        required_claims=required_claims,
        forbidden_claims=payload.forbidden_claims,
        open_questions=payload.open_questions,
        input_fingerprint=input_fingerprint,
        status="ready" if evidence_ids and source_urls else "blocked",
    )
    action.stage = "brief_ready" if brief.status == "ready" else "blocked"
    action.status = "in_progress"
    action.blocked_reason = None if brief.status == "ready" else "No real source-backed evidence is attached"
    db.add(brief)
    db.add(
        GeoActionEvent(
            workspace_id=workspace_id,
            action_id=action.id,
            event_type="brief_created",
            from_stage="selected",
            to_stage=action.stage,
            actor_type="user",
            actor_user_id=user.id,
            detail={"brief_status": brief.status, "evidence_ids": evidence_ids, "source_count": len(source_urls)},
        )
    )
    db.commit()
    db.refresh(brief)
    return brief


@router.get(
    "/workspaces/{workspace_id}/actions/{action_id}/briefs",
    response_model=list[ContentBriefRead],
)
def list_content_briefs(
    workspace_id: int,
    action_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    scoped_or_404(db, GeoOptimizationAction, workspace_id, action_id)
    return list(
        db.scalars(
            select(GeoContentBrief)
            .where(GeoContentBrief.workspace_id == workspace_id, GeoContentBrief.action_id == action_id)
            .order_by(GeoContentBrief.id.desc())
        )
    )


@router.get(
    "/workspaces/{workspace_id}/actions/{action_id}/briefs/{brief_id}/assets",
    response_model=list[ContentAssetRead],
)
def list_content_assets(
    workspace_id: int,
    action_id: int,
    brief_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    scoped_or_404(db, GeoOptimizationAction, workspace_id, action_id)
    brief = scoped_or_404(db, GeoContentBrief, workspace_id, brief_id)
    if brief.action_id != action_id:
        raise HTTPException(status_code=404, detail="Content brief not found")
    return list(
        db.scalars(
            select(GeoContentAsset)
            .where(GeoContentAsset.workspace_id == workspace_id, GeoContentAsset.brief_id == brief_id)
            .order_by(GeoContentAsset.version.desc(), GeoContentAsset.id.desc())
        )
    )


@router.post(
    "/workspaces/{workspace_id}/actions/{action_id}/briefs/{brief_id}/assets/{asset_id}/variants",
    response_model=list[PlatformVariantRead],
    status_code=201,
)
def create_platform_variants(
    workspace_id: int,
    action_id: int,
    brief_id: int,
    asset_id: int,
    payload: PlatformVariantCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    action = scoped_or_404(db, GeoOptimizationAction, workspace_id, action_id)
    brief = scoped_or_404(db, GeoContentBrief, workspace_id, brief_id)
    asset = scoped_or_404(db, GeoContentAsset, workspace_id, asset_id)
    if brief.action_id != action.id or asset.brief_id != brief.id:
        raise HTTPException(status_code=404, detail="Content asset not found")
    variants: list[GeoPlatformVariant] = []
    for platform_key in dict.fromkeys(payload.platform_keys):
        existing = db.scalar(
            select(GeoPlatformVariant).where(
                GeoPlatformVariant.content_asset_id == asset.id,
                GeoPlatformVariant.platform_key == platform_key,
                GeoPlatformVariant.version == 1,
            )
        )
        if existing:
            variants.append(existing)
            continue
        variant = adapt_asset(asset, workspace_id=workspace_id, platform_key=platform_key)
        db.add(variant)
        db.flush()
        variants.append(variant)
    previous_stage = action.stage
    action.stage = "reviewing"
    db.add(
        GeoActionEvent(
            workspace_id=workspace_id,
            action_id=action.id,
            event_type="platform_variants_created",
            from_stage=previous_stage,
            to_stage="reviewing",
            actor_type="user",
            actor_user_id=user.id,
            detail={"asset_id": asset.id, "platform_keys": list(dict.fromkeys(payload.platform_keys))},
        )
    )
    db.commit()
    return variants


def _distribution_read(db: Session, run: GeoDistributionRun) -> dict:
    targets = list(
        db.scalars(
            select(GeoDistributionTarget)
            .where(GeoDistributionTarget.distribution_run_id == run.id)
            .order_by(GeoDistributionTarget.id.asc())
        )
    )
    return {"id": run.id, "targets": targets, **run.__dict__}


@router.post(
    "/workspaces/{workspace_id}/distribution-runs",
    response_model=DistributionRunRead,
    status_code=201,
)
def create_distribution_run(
    workspace_id: int,
    payload: DistributionRunCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    asset = scoped_or_404(db, GeoContentAsset, workspace_id, payload.content_asset_id)
    action = db.scalar(
        select(GeoOptimizationAction)
        .join(GeoContentBrief, GeoContentBrief.action_id == GeoOptimizationAction.id)
        .where(GeoContentBrief.id == asset.brief_id, GeoOptimizationAction.workspace_id == workspace_id)
    )
    existing = db.scalar(
        select(GeoDistributionRun).where(
            GeoDistributionRun.workspace_id == workspace_id,
            GeoDistributionRun.idempotency_key == payload.idempotency_key,
        )
    )
    if existing:
        return _distribution_read(db, existing)
    variants = {
        variant.platform_key: variant
        for variant in db.scalars(
            select(GeoPlatformVariant).where(
                GeoPlatformVariant.content_asset_id == asset.id,
                GeoPlatformVariant.platform_key.in_(payload.platform_keys),
                GeoPlatformVariant.version == 1,
            )
        )
    }
    run = GeoDistributionRun(
        workspace_id=workspace_id,
        action_id=action.id if action else None,
        content_asset_id=asset.id,
        requested_platforms=list(dict.fromkeys(payload.platform_keys)),
        stage="awaiting_adapter",
        idempotency_key=payload.idempotency_key,
        status="blocked",
        requested_by_user_id=user.id,
    )
    db.add(run)
    db.flush()
    for platform_key in dict.fromkeys(payload.platform_keys):
        variant = variants.get(platform_key)
        db.add(
            GeoDistributionTarget(
                distribution_run_id=run.id,
                platform_variant_id=variant.id if variant else None,
                platform_key=platform_key,
                request_status="not_started",
                draft_readback_status="not_started",
                waiting_human_reason="文章同步助手 MCP 适配器尚未配置；未发送外部请求。",
                blocked_reason="sync_adapter_not_configured",
            )
        )
    if action:
        previous_stage = action.stage
        action.stage = "blocked"
        action.blocked_reason = "sync_adapter_not_configured"
        db.add(
            GeoActionEvent(
                workspace_id=workspace_id,
                action_id=action.id,
                event_type="distribution_blocked",
                from_stage=previous_stage,
                to_stage="blocked",
                actor_type="user",
                actor_user_id=user.id,
                detail={"distribution_run_id": run.id, "reason": "sync_adapter_not_configured"},
            )
        )
    db.commit()
    db.refresh(run)
    return _distribution_read(db, run)


def _nested_value(payload: object, keys: set[str]) -> str | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in keys and isinstance(value, str) and value.strip():
                return value.strip()
            found = _nested_value(value, keys)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _nested_value(value, keys)
            if found:
                return found
    return None


@router.post(
    "/workspaces/{workspace_id}/distribution-runs/{run_id}/request",
    response_model=DistributionRunRead,
)
def request_distribution_run(
    workspace_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    run = scoped_or_404(db, GeoDistributionRun, workspace_id, run_id)
    server_path, token = resolve_article_sync_credentials(db, workspace_id)
    adapter = get_article_sync_adapter(server_path=server_path, token=token)
    targets = list(
        db.scalars(
            select(GeoDistributionTarget)
            .where(GeoDistributionTarget.distribution_run_id == run.id)
            .order_by(GeoDistributionTarget.id.asc())
        )
    )
    accepted = 0
    for target in targets:
        variant = db.get(GeoPlatformVariant, target.platform_variant_id) if target.platform_variant_id else None
        if variant is None:
            target.request_status = "blocked"
            target.blocked_reason = "platform_variant_missing"
            continue
        try:
            _result = adapter.request_draft(
                platform_key=target.platform_key,
                title=variant.title,
                body_markdown=variant.body_markdown,
            )
        except RuntimeError as exc:
            target.request_status = "blocked"
            target.blocked_reason = str(exc)[:200]
            target.last_error_code = "mcp_request_failed"
            continue
        target.request_status = "mcp_request_accepted"
        target.draft_readback_status = "pending"
        target.waiting_human_reason = "MCP 已接受请求；必须读回真实草稿对象后才算保存。"
        accepted += 1
        target.response_artifact_uri = f"mcp://article-sync/request/{run.id}/{target.id}"
    run.stage = "awaiting_readback" if accepted else "blocked"
    run.status = "pending" if accepted else "blocked"
    db.add(
        GeoActionEvent(
            workspace_id=workspace_id,
            action_id=run.action_id,
            event_type="distribution_mcp_requested",
            from_stage="blocked",
            to_stage="awaiting_readback" if accepted else "blocked",
            actor_type="user",
            actor_user_id=user.id,
            detail={"distribution_run_id": run.id, "accepted_target_count": accepted},
        )
    )
    db.commit()
    db.refresh(run)
    return _distribution_read(db, run)


@router.post(
    "/workspaces/{workspace_id}/distribution-runs/{run_id}/targets/{target_id}/readback",
    response_model=DistributionRunRead,
)
def readback_distribution_target(
    workspace_id: int,
    run_id: int,
    target_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    run = scoped_or_404(db, GeoDistributionRun, workspace_id, run_id)
    target = db.get(GeoDistributionTarget, target_id)
    if target is None or target.distribution_run_id != run.id:
        raise HTTPException(status_code=404, detail="Distribution target not found")
    server_path, token = resolve_article_sync_credentials(db, workspace_id)
    adapter = get_article_sync_adapter(server_path=server_path, token=token)
    try:
        result = adapter.read_draft(platform_key=target.platform_key, candidate_url=target.candidate_draft_url)
    except RuntimeError as exc:
        target.draft_readback_status = "blocked"
        target.blocked_reason = str(exc)[:200]
        target.last_error_code = "mcp_readback_failed"
    else:
        target.draft_readback_status = "readback_received"
        target.readback_artifact_uri = f"mcp://article-sync/readback/{run.id}/{target.id}"
        target.draft_url = _nested_value(result, {"draft_url", "url", "draftUrl"})
        target.external_draft_id = _nested_value(result, {"external_draft_id", "draft_id", "id"})
        if target.draft_url or target.external_draft_id:
            target.draft_readback_status = "draft_saved"
            target.request_status = "draft_saved"
            target.waiting_human_reason = None
    all_saved = bool(
        targets := list(
            db.scalars(
                select(GeoDistributionTarget).where(GeoDistributionTarget.distribution_run_id == run.id)
            )
        )
    ) and all(item.draft_readback_status == "draft_saved" for item in targets)
    run.stage = "draft_saved" if all_saved else "awaiting_readback"
    run.status = "draft_saved" if all_saved else "pending"
    db.commit()
    db.refresh(run)
    return _distribution_read(db, run)


@router.post(
    "/workspaces/{workspace_id}/actions/{action_id}/briefs/{brief_id}/generate",
    response_model=QueueJobRead,
    status_code=202,
)
def enqueue_content_generation(
    workspace_id: int,
    action_id: int,
    brief_id: int,
    payload: ContentGenerateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    action = scoped_or_404(db, GeoOptimizationAction, workspace_id, action_id)
    brief = scoped_or_404(db, GeoContentBrief, workspace_id, brief_id)
    if brief.action_id != action_id:
        raise HTTPException(status_code=404, detail="Content brief not found")
    provider = db.get(LLMProvider, payload.provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="LLM provider not found")
    diagnostic = diagnose_provider(provider)
    if not diagnostic.get("auth_ready"):
        raise HTTPException(status_code=400, detail="请先配置并验证内容生成 Provider 的 API Key")
    existing = next(
        (
            job
            for job in db.scalars(
                select(QueueJob)
                .where(QueueJob.job_type == "geo_content.generate", QueueJob.status.in_(["pending", "running"]))
                .order_by(QueueJob.id.desc())
            )
            if int((job.payload_json or {}).get("brief_id") or 0) == brief_id
            and str((job.payload_json or {}).get("platform_key") or "official_site") == payload.platform_key
        ),
        None,
    )
    if existing:
        return existing
    previous_stage = action.stage
    action.stage = "generating"
    action.status = "in_progress"
    action.blocked_reason = None
    job = QueueJob(
        job_type="geo_content.generate",
        status="pending",
        priority=15,
        scheduled_at=datetime.now(timezone.utc),
        max_attempts=1,
        payload_json={
            "project_id": 0,
            "workspace_id": workspace_id,
            "action_id": action_id,
            "brief_id": brief_id,
            "provider_id": provider.id,
            "platform_key": payload.platform_key,
            "actor_user_id": user.id,
        },
    )
    db.add(job)
    db.flush()
    db.add(
        GeoActionEvent(
            workspace_id=workspace_id,
            action_id=action.id,
            job_id=job.id,
            event_type="content_generation_queued",
            from_stage=previous_stage,
            to_stage="generating",
            actor_type="user",
            actor_user_id=user.id,
            detail={"brief_id": brief_id, "provider_id": provider.id, "platform_key": payload.platform_key},
        )
    )
    db.commit()
    db.refresh(job)
    return job


@router.get("/workspaces/{workspace_id}/actions", response_model=list[ActionRead])
def list_actions(
    workspace_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    workspace_or_404(db, user, workspace_id)
    return list(
        db.scalars(
            select(GeoOptimizationAction)
            .where(GeoOptimizationAction.workspace_id == workspace_id)
            .order_by(GeoOptimizationAction.id.desc())
        )
    )


@router.patch("/workspaces/{workspace_id}/actions/{action_id}", response_model=ActionRead)
def update_action(
    workspace_id: int,
    action_id: int,
    payload: ActionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    action = scoped_or_404(db, GeoOptimizationAction, workspace_id, action_id)
    if payload.status == "closed" and not db.scalar(
        select(GeoReobservation).where(GeoReobservation.action_id == action.id)
    ):
        raise HTTPException(
            status_code=422,
            detail="A re-observation and conclusion are required before closing an action",
        )
    if payload.status:
        action.status = payload.status
    db.commit()
    db.refresh(action)
    return action


@router.post("/workspaces/{workspace_id}/actions/{action_id}/re-observations", status_code=201)
def create_reobservation(
    workspace_id: int,
    action_id: int,
    payload: ReobservationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    action = scoped_or_404(db, GeoOptimizationAction, workspace_id, action_id)
    if db.scalar(select(GeoReobservation).where(GeoReobservation.action_id == action.id)):
        raise HTTPException(status_code=409, detail="Action already has a re-observation")
    run = scoped_or_404(db, GeoObservationRun, workspace_id, payload.run_id)
    evidence = scoped_or_404(db, GeoEvidence, workspace_id, payload.evidence_id)
    if evidence.run_id != run.id:
        raise HTTPException(
            status_code=422, detail="Evidence must belong to the declared re-observation run"
        )
    row = GeoReobservation(
        action_id=action.id,
        workspace_id=workspace_id,
        run_id=run.id,
        evidence_id=evidence.id,
        conclusion=payload.conclusion,
        measured_delta=payload.measured_delta,
    )
    action.status = "verified"
    db.add(row)
    db.commit()
    return {"id": row.id, "action_id": action.id, "status": action.status}


@router.get("/workspaces/{workspace_id}/brand-facts", response_model=list[BrandFactRead])
def list_brand_facts(
    workspace_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    workspace_or_404(db, user, workspace_id)
    return list(
        db.scalars(
            select(GeoBrandFact)
            .where(GeoBrandFact.workspace_id == workspace_id)
            .order_by(GeoBrandFact.id.desc())
        )
    )


@router.post(
    "/workspaces/{workspace_id}/brand-facts", response_model=BrandFactRead, status_code=201
)
def create_brand_fact(
    workspace_id: int,
    payload: BrandFactCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    fact = GeoBrandFact(workspace_id=workspace_id, **payload.model_dump())
    db.add(fact)
    db.commit()
    db.refresh(fact)
    return fact


@router.get("/workspaces/{workspace_id}/content-audits", response_model=list[ContentAuditRead])
def list_content_audits(
    workspace_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    workspace_or_404(db, user, workspace_id)
    return list(
        db.scalars(
            select(GeoContentAudit)
            .where(GeoContentAudit.workspace_id == workspace_id)
            .order_by(GeoContentAudit.id.desc())
        )
    )


@router.post(
    "/workspaces/{workspace_id}/content-audits", response_model=ContentAuditRead, status_code=201
)
def create_content_audit(
    workspace_id: int,
    payload: ContentAuditCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    result = audit_content_snapshot(payload.title, payload.body, payload.source_urls)
    fingerprint = sha256(
        "\n".join(
            [payload.title.strip(), payload.body.strip(), *sorted(payload.source_urls)]
        ).encode()
    ).hexdigest()
    audit = GeoContentAudit(
        workspace_id=workspace_id,
        target_url=payload.target_url,
        content_fingerprint=fingerprint,
        audit_version=result["engine"],
        score=result["score"],
        checks=result["checks"],
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit
