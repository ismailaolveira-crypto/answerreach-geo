import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
from pathlib import Path
import secrets
from time import perf_counter
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
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
    GeoAgentArtifact,
    GeoAgentEvent,
    GeoAgentRun,
    GeoBrandFact,
    GeoBrowserAccount,
    GeoContentAudit,
    GeoContentAsset,
    GeoContentBrief,
    GeoContentClaim,
    GeoContentReview,
    GeoCompetitorInsightSnapshot,
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
    GeoWebsiteAudit,
)
from app.models.user import User
from app.schemas.search import QueueJobRead
from app.v1.schemas import (
    ActionCreate,
    ActionEvidenceSummaryRead,
    ActionEventRead,
    ActionOpportunityDiscoverRequest,
    ActionOpportunityRead,
    ActionOpportunityScopeRead,
    ActionRead,
    ActionStageUpdate,
    ActionUpdate,
    AgentArtifactRead,
    AgentEventRead,
    AgentRunProgressRead,
    AgentRevisionRequest,
    AgentRunCreate,
    AgentRunRead,
    AgentRuntimeRead,
    AgentRuntimeTestRead,
    BrandFactCreate,
    BrandFactRead,
    BrandFactSourceCandidatesRead,
    BrandFactUpdate,
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
    ContentReviewDecision,
    ContentLibraryItemRead,
    ContentReviewPackageRead,
    ContentGenerateRequest,
    DistributionRunCreate,
    DistributionClientResults,
    DistributionRunRead,
    HumanPublicationRecord,
    HumanDraftReadbackRecord,
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
    ActionRetestRead,
    ActionWorkbenchStateRead,
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
    WebsiteAuditOverviewRead,
    WebsiteAuditRead,
    YaoDatasetImport,
    YaoDeepSeekDatasetImport,
    YaoDoubaoDatasetImport,
)
from app.services.llm_provider import diagnose_provider, get_search_provider
from app.services.audit import record_audit_log
from app.services.usage import enforce_monthly_search_budget, record_usage
from app.v1.competitor_comparison import (
    MATCH_RULE_VERSION,
    brand_configs,
    build_competitor_comparison,
)
from app.v1.competitor_insight import CompetitorInsightError, generate_competitor_insight
from app.v1.evidence_analysis import analyze_brand_status
from app.v1.scoring import SCORING_VERSION, audit_content_snapshot, score_evidence
from app.v1.source_map import build_source_map
from app.v1.question_analysis import build_question_analysis
from app.v1.yao_adapter import normalize_yao_stage1_dataset
from app.v1.action_opportunities import (
    discover_opportunities,
    materialize_website_opportunity,
    valid_action_evidence,
)
from app.v1.action_retests import build_batch_metrics, compare_batches
from app.v1.brand_facts import (
    BRAND_FACT_CANDIDATES_DISCOVERED_ACTION,
    BRAND_FACT_VERIFICATION_ACTION,
    BRAND_FACT_VERIFICATION_FAILED_ACTION,
    brand_fact_read,
    statement_fingerprint,
    verified_active_brand_facts,
)
from app.v1.platform_adaptation import adapt_asset
from app.v1.website_audit import (
    BrandFactSourceVerificationError,
    PublicationVerificationError,
    WebsiteAuditTargetError,
    audit_website,
    discover_brand_fact_source_candidates,
    verify_brand_fact_source,
    verify_publication_page,
)
from app.services.article_sync_adapter import get_article_sync_adapter
from app.services.codex_agent_runtime import (
    LocalCodexRuntime,
    diagnose_local_codex,
    invalidate_local_codex_diagnostic_cache,
)
from app.db.session import SessionLocal
from app.v1.agent_orchestration import (
    ARTIFACT_ROOT,
    action_evidence_inputs,
    append_agent_event,
    capture_agent_visuals,
)
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
AGENT_ARTIFACT_ROOT = API_ROOT / "private_artifacts" / "agent-runs"


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
    db.refresh(ledger_batch)
    return _official_api_batch_read(db, ledger_batch)


def _observation_task_status(status: str) -> str:
    return "success" if status in {"completed", "succeeded", "success"} else status


def _official_api_batch_tasks(db: Session, batch: GeoObservationBatch) -> list[GeoObservationTask]:
    return list(
        db.scalars(
            select(GeoObservationTask)
            .where(
                GeoObservationTask.workspace_id == batch.workspace_id,
                GeoObservationTask.batch_id == batch.id,
            )
            .order_by(GeoObservationTask.id)
        )
    )


def _official_api_batch_summary(
    db: Session,
    batch: GeoObservationBatch,
    *,
    tasks: list[GeoObservationTask] | None = None,
) -> dict:
    task_rows = tasks if tasks is not None else _official_api_batch_tasks(db, batch)
    normalized_statuses = [_observation_task_status(task.status) for task in task_rows]
    counts = {
        status: normalized_statuses.count(status)
        for status in ("pending", "running", "success", "failed")
    }
    settled = counts["success"] + counts["failed"]
    total = len(task_rows) or int(batch.total_tasks or 0)
    if total and settled >= total:
        status = (
            "success"
            if counts["failed"] == 0
            else "failed"
            if counts["success"] == 0
            else "partial"
        )
    elif counts["running"] or settled:
        status = "running"
    elif batch.status in {"failed", "partial"}:
        status = batch.status
    else:
        status = "pending"
    return {
        "batch_id": batch.id,
        "source_type": batch.source_type,
        "status": status,
        "provider_count": batch.provider_count,
        "question_count": batch.question_count,
        "repeat_count": batch.repeat_count,
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
        "finished_at": batch.completed_at,
    }


def _official_api_batch_read(
    db: Session,
    batch: GeoObservationBatch,
    *,
    task_page: int = 1,
    task_page_size: int = 125,
) -> dict:
    task_rows = _official_api_batch_tasks(db, batch)

    def group_counts(matching: list[GeoObservationTask]) -> dict[str, int]:
        statuses = [_observation_task_status(task.status) for task in matching]
        return {item: statuses.count(item) for item in ("pending", "running", "success", "failed")}

    provider_groups: list[dict] = []
    provider_keys: list[tuple[int | None, str, str]] = []
    for task in task_rows:
        identity = (task.provider_id, task.model_key, task.model_label)
        if identity not in provider_keys:
            provider_keys.append(identity)
    for index, (provider_id, model_key, model_label) in enumerate(provider_keys):
        matching = [
            task
            for task in task_rows
            if (task.provider_id, task.model_key, task.model_label)
            == (provider_id, model_key, model_label)
        ]
        counts = group_counts(matching)
        provider_groups.append(
            {
                "id": provider_id if provider_id is not None else -(index + 1),
                "key": model_key,
                "label": model_label,
                "total": len(matching),
                "pending": counts["pending"],
                "running": counts["running"],
                "succeeded": counts["success"],
                "failed": counts["failed"],
            }
        )

    question_groups: list[dict] = []
    question_ids = list(dict.fromkeys(task.question_plan_id for task in task_rows))
    for question_id in question_ids:
        matching = [task for task in task_rows if task.question_plan_id == question_id]
        counts = group_counts(matching)
        question_groups.append(
            {
                "id": question_id,
                "key": str(question_id),
                "label": matching[0].question_text_snapshot,
                "total": len(matching),
                "pending": counts["pending"],
                "running": counts["running"],
                "succeeded": counts["success"],
                "failed": counts["failed"],
            }
        )

    def duration_seconds(task: GeoObservationTask) -> int | None:
        if task.started_at is None:
            return None
        endpoint = task.completed_at or (
            datetime.now(timezone.utc) if task.status == "running" else None
        )
        if endpoint is None:
            return None
        started_at = _as_utc(task.started_at)
        finished_at = _as_utc(endpoint)
        return max(0, round((finished_at - started_at).total_seconds()))

    task_total = len(task_rows)
    task_start = (task_page - 1) * task_page_size
    selected_tasks = task_rows[task_start : task_start + task_page_size]
    tasks = []
    for task in selected_tasks:
        tasks.append(
            {
                "job_id": task.id,
                "provider_id": task.provider_id or 0,
                "provider_key": task.model_key,
                "provider_label": task.model_label,
                "question_plan_id": task.question_plan_id,
                "question_label": task.question_text_snapshot,
                "repeat_index": task.repeat_index,
                "status": _observation_task_status(task.status),
                "evidence_id": task.evidence_id,
                "error_message": task.error_detail or task.error_code,
                "started_at": task.started_at,
                "finished_at": task.completed_at,
                "duration_seconds": duration_seconds(task),
            }
        )

    evidence_ids = [task.evidence_id for task in task_rows if task.evidence_id is not None]
    errors = list(
        dict.fromkeys(
            task.error_detail or task.error_code
            for task in task_rows
            if task.error_detail or task.error_code
        )
    )
    return {
        **_official_api_batch_summary(db, batch, tasks=task_rows),
        "provider_groups": provider_groups,
        "question_groups": question_groups,
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
    filters = (GeoObservationBatch.workspace_id == workspace_id,)
    total = int(db.scalar(select(func.count(GeoObservationBatch.id)).where(*filters)) or 0)
    batches = list(
        db.scalars(
            select(GeoObservationBatch)
            .where(*filters)
            .order_by(GeoObservationBatch.created_at.desc(), GeoObservationBatch.id.desc())
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
    """Return the most recent canonical observation batch for map restoration.

    The decision map is allowed to be revisited without a batch id in the URL.
    Returning the latest batch keeps the last result visible after navigation,
    refresh, or switching desktop spaces; a new run only replaces it once the
    user explicitly submits another measurement.
    """
    workspace_or_404(db, user, workspace_id)
    batch = db.scalar(
        select(GeoObservationBatch)
        .where(GeoObservationBatch.workspace_id == workspace_id)
        .order_by(GeoObservationBatch.created_at.desc(), GeoObservationBatch.id.desc())
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
    batch = db.get(GeoObservationBatch, batch_id)
    if batch is None or batch.workspace_id != workspace_id:
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


def _fingerprint_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _normalize_competitor_model_key(value: str | None) -> str:
    normalized = (value or "").strip()
    return "" if normalized == "all" else normalized


def _competitor_insight_scope_fingerprint(
    *,
    workspace_id: int,
    user_id: int,
    period_days: int,
    model_key: str,
    question_plan_id: int | None,
    evidence_limit: int,
) -> str:
    return _fingerprint_json(
        {
            "workspace_id": workspace_id,
            "user_id": user_id,
            "period_days": period_days,
            "model_key": model_key,
            "question_plan_id": question_plan_id,
            "evidence_limit": evidence_limit,
        }
    )


def _competitor_insight_input_fingerprint(
    workspace: GeoWorkspace,
    real_rows: list[GeoEvidence],
    questions: list[GeoQuestionPlan],
) -> str:
    return _fingerprint_json(
        {
            "matching_rule_version": MATCH_RULE_VERSION,
            "brand": {
                "name": workspace.brand_name,
                "aliases": workspace.brand_aliases or [],
                "catalog": [
                    {
                        "key": item.key,
                        "name": item.canonical_name,
                        "aliases": item.aliases,
                        "is_baseline": item.is_baseline,
                    }
                    for item in brand_configs(workspace)
                ],
            },
            "questions": [
                {"id": item.id, "text": item.question_text, "importance": item.importance}
                for item in sorted(questions, key=lambda row: row.id)
            ],
            "evidence": [
                {"id": item.id, "answer_hash": item.answer_hash}
                for item in sorted(real_rows, key=lambda row: row.id)
            ],
        }
    )


def _load_competitor_insight_scope(
    db: Session,
    workspace: GeoWorkspace,
    *,
    period_days: int,
    model_key: str,
    question_plan_id: int | None,
    evidence_limit: int,
) -> dict:
    selected_question = None
    if question_plan_id is not None:
        selected_question = scoped_or_404(db, GeoQuestionPlan, workspace.id, question_plan_id)
    effective_to = datetime.now(timezone.utc)
    effective_from = effective_to - timedelta(days=period_days)
    scoped_query = select(GeoEvidence).where(
        GeoEvidence.workspace_id == workspace.id,
        GeoEvidence.captured_at >= effective_from,
        GeoEvidence.captured_at <= effective_to,
    )
    if model_key:
        scoped_query = scoped_query.where(GeoEvidence.model_key == model_key)
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
                GeoQuestionPlan.workspace_id == workspace.id,
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
    model_label = "全部已测模型"
    if model_key:
        model_label = next(
            (row.model_label for row in real_rows if row.model_key == model_key), model_key
        )
    return {
        "comparison": comparison,
        "input_fingerprint": _competitor_insight_input_fingerprint(
            workspace, real_rows, questions
        ),
        "model_label": model_label,
        "question_label": (
            selected_question.question_text if selected_question is not None else "全部已选问题"
        ),
        "real_rows": real_rows,
    }


def _competitor_insight_snapshot_response(
    snapshot: GeoCompetitorInsightSnapshot,
    *,
    is_stale: bool,
) -> dict:
    return {
        **snapshot.payload,
        "snapshot_id": snapshot.id,
        "persisted": True,
        "is_stale": is_stale,
        "source_evidence_count": len(snapshot.source_evidence_ids or []),
    }


@router.get(
    "/workspaces/{workspace_id}/competitor-insights",
    response_model=CompetitorInsightRead | None,
)
def get_latest_workspace_competitor_insight(
    workspace_id: int,
    period_days: int = Query(90, ge=1, le=3650),
    model_key: str | None = Query(default=None, min_length=1, max_length=120),
    question_plan_id: int | None = Query(default=None, ge=1),
    evidence_limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Restore the latest report for this account and exact filter scope."""
    workspace = workspace_or_404(db, user, workspace_id)
    normalized_model_key = _normalize_competitor_model_key(model_key)
    scope_fingerprint = _competitor_insight_scope_fingerprint(
        workspace_id=workspace_id,
        user_id=user.id,
        period_days=period_days,
        model_key=normalized_model_key,
        question_plan_id=question_plan_id,
        evidence_limit=evidence_limit,
    )
    snapshot = db.scalar(
        select(GeoCompetitorInsightSnapshot)
        .where(
            GeoCompetitorInsightSnapshot.workspace_id == workspace_id,
            GeoCompetitorInsightSnapshot.created_by_user_id == user.id,
            GeoCompetitorInsightSnapshot.scope_fingerprint == scope_fingerprint,
        )
        .order_by(
            GeoCompetitorInsightSnapshot.generated_at.desc(),
            GeoCompetitorInsightSnapshot.id.desc(),
        )
    )
    if snapshot is None:
        return None
    current_scope = _load_competitor_insight_scope(
        db,
        workspace,
        period_days=period_days,
        model_key=normalized_model_key,
        question_plan_id=question_plan_id,
        evidence_limit=evidence_limit,
    )
    return _competitor_insight_snapshot_response(
        snapshot,
        is_stale=snapshot.input_fingerprint != current_scope["input_fingerprint"],
    )


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
    """Generate and persist a derived report without altering observation metrics."""
    workspace = workspace_or_404(db, user, workspace_id)
    model_key = _normalize_competitor_model_key(payload.model_key)
    current_scope = _load_competitor_insight_scope(
        db,
        workspace,
        period_days=payload.period_days,
        model_key=model_key,
        question_plan_id=payload.question_plan_id,
        evidence_limit=payload.evidence_limit,
    )
    try:
        generated = generate_competitor_insight(
            current_scope["comparison"],
            api_key=get_settings().deepseek_api_key,
            selected_question_id=payload.question_plan_id,
            selected_question_label=current_scope["question_label"],
            selected_model_label=current_scope["model_label"],
            selected_period_label=(
                "全部归档" if payload.period_days == 3650 else f"近 {payload.period_days} 天"
            ),
        )
    except CompetitorInsightError as error:
        status_code = 503 if "API Key" in str(error) else 502
        raise HTTPException(status_code=status_code, detail=str(error)) from error

    generated_at = generated["generated_at"]
    if isinstance(generated_at, str):
        generated_at = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    serialized_payload = {
        "provider": generated["provider"],
        "model": generated["model"],
        "generated_at": generated_at.isoformat(),
        "scope": generated["scope"],
        "analysis": generated["analysis"],
    }
    linked_evidence_ids = sorted(
        {
            evidence_id
            for finding in generated["analysis"].get("findings", [])
            for evidence_id in finding.get("evidence_ids", [])
            if isinstance(evidence_id, int)
        }
    )
    snapshot = GeoCompetitorInsightSnapshot(
        workspace_id=workspace_id,
        created_by_user_id=user.id,
        period_days=payload.period_days,
        model_key=model_key,
        question_plan_id=payload.question_plan_id,
        evidence_limit=payload.evidence_limit,
        scope_fingerprint=_competitor_insight_scope_fingerprint(
            workspace_id=workspace_id,
            user_id=user.id,
            period_days=payload.period_days,
            model_key=model_key,
            question_plan_id=payload.question_plan_id,
            evidence_limit=payload.evidence_limit,
        ),
        input_fingerprint=current_scope["input_fingerprint"],
        provider=generated["provider"],
        model=generated["model"],
        payload=serialized_payload,
        source_evidence_ids=[row.id for row in current_scope["real_rows"]],
        linked_evidence_ids=linked_evidence_ids,
        generated_at=generated_at,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return _competitor_insight_snapshot_response(snapshot, is_stale=False)


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
    measurement_batch: GeoObservationBatch | None = None
    measurement_evidence_ids: set[int] | None = None
    if batch_id is not None:
        measurement_batch = db.get(GeoObservationBatch, batch_id)
        if measurement_batch is None or measurement_batch.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="Observation batch not found")
        measurement_evidence_ids = {
            int(value)
            for value in db.scalars(
                select(GeoObservationTask.evidence_id).where(
                    GeoObservationTask.workspace_id == workspace_id,
                    GeoObservationTask.batch_id == measurement_batch.id,
                    GeoObservationTask.evidence_id.is_not(None),
                )
            )
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
            "batch_finished_at": measurement_batch.completed_at if measurement_batch else None,
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


@router.get(
    "/workspaces/{workspace_id}/action-opportunities/scope",
    response_model=ActionOpportunityScopeRead,
)
def get_action_opportunity_scope(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return only completed ledger batches that contain action-eligible evidence."""

    workspace_or_404(db, user, workspace_id)
    batches = list(
        db.scalars(
            select(GeoObservationBatch)
            .where(
                GeoObservationBatch.workspace_id == workspace_id,
                GeoObservationBatch.status.in_(("completed", "succeeded")),
            )
            .order_by(GeoObservationBatch.id.desc())
            .limit(40)
        )
    )
    batch_ids = [batch.id for batch in batches]
    tasks = list(
        db.scalars(
            select(GeoObservationTask).where(
                GeoObservationTask.workspace_id == workspace_id,
                GeoObservationTask.batch_id.in_(batch_ids or [-1]),
                GeoObservationTask.status.in_(("completed", "succeeded")),
                GeoObservationTask.evidence_id.is_not(None),
            )
        )
    )
    evidence_ids = [int(task.evidence_id) for task in tasks if task.evidence_id]
    evidence_by_id = {
        row.id: row
        for row in db.scalars(
            select(GeoEvidence).where(
                GeoEvidence.workspace_id == workspace_id,
                GeoEvidence.id.in_(evidence_ids or [-1]),
            )
        )
    }
    eligible_tasks_by_batch: dict[int, list[GeoObservationTask]] = defaultdict(list)
    model_labels: dict[str, str] = {}
    question_ids: set[int] = set()
    for task in tasks:
        evidence = evidence_by_id.get(int(task.evidence_id or 0))
        if evidence is None or not valid_action_evidence(evidence):
            continue
        eligible_tasks_by_batch[task.batch_id].append(task)
        model_labels[task.model_key] = task.model_label
        question_ids.add(task.question_plan_id)
    questions = {
        question.id: question
        for question in db.scalars(
            select(GeoQuestionPlan).where(
                GeoQuestionPlan.workspace_id == workspace_id,
                GeoQuestionPlan.id.in_(question_ids or [-1]),
                GeoQuestionPlan.active.is_(True),
            )
        )
    }
    scope_batches = []
    for batch in batches:
        eligible_tasks = eligible_tasks_by_batch.get(batch.id, [])
        if not eligible_tasks:
            continue
        scope_batches.append(
            {
                "id": batch.id,
                "status": batch.status,
                "created_at": batch.created_at,
                "completed_at": batch.completed_at,
                "eligible_evidence_count": len(eligible_tasks),
                "model_keys": sorted({task.model_key for task in eligible_tasks}),
                "question_plan_ids": sorted(
                    {task.question_plan_id for task in eligible_tasks if task.question_plan_id in questions}
                ),
            }
        )
    scope_batches = scope_batches[:12]
    return {
        "latest_batch_id": scope_batches[0]["id"] if scope_batches else None,
        "batches": scope_batches,
        "models": [
            {"key": key, "label": label}
            for key, label in sorted(model_labels.items(), key=lambda item: item[1])
        ],
        "questions": [
            {"id": question.id, "label": question.question_text}
            for question in sorted(
                questions.values(), key=lambda item: (-item.importance, item.id)
            )
        ],
        "evidence_gate": "completed_task+real_answer+search_event+source_url+raw_artifact",
    }


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
    selected_model_keys = sorted({value.strip() for value in payload.model_keys if value.strip()})
    if effective_batch_id and selected_model_keys:
        available_model_keys = set(
            db.scalars(
                select(GeoObservationTask.model_key)
                .where(
                    GeoObservationTask.workspace_id == workspace_id,
                    GeoObservationTask.batch_id == effective_batch_id,
                    GeoObservationTask.status.in_(("completed", "succeeded")),
                )
                .distinct()
            )
        )
        unavailable = sorted(set(selected_model_keys) - available_model_keys)
        if unavailable:
            raise HTTPException(
                status_code=422,
                detail=f"所选批次不包含模型：{', '.join(unavailable)}",
            )
    opportunities = discover_opportunities(
        db,
        workspace,
        batch_id=effective_batch_id,
        question_plan_ids=payload.question_plan_ids or None,
        model_keys=selected_model_keys or None,
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
                "model_keys": selected_model_keys,
                "question_plan_ids": payload.question_plan_ids,
                "opportunity_count": len(opportunities),
                "evidence_gate": (
                    "completed_task+real_answer+search_event+source_url+raw_artifact"
                ),
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
    batch_id: int | None = Query(default=None, ge=1),
    model_key: str | None = Query(default=None, min_length=1, max_length=120),
    question_plan_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    query = select(GeoActionOpportunity).where(GeoActionOpportunity.workspace_id == workspace_id)
    if status:
        query = query.where(GeoActionOpportunity.status == status)
    else:
        query = query.where(GeoActionOpportunity.status.in_(["open", "selected"]))
    rows = list(
        db.scalars(
            query.order_by(
                GeoActionOpportunity.priority_score.desc(), GeoActionOpportunity.id.desc()
            )
        )
    )
    if batch_id is not None:
        rows = [
            row for row in rows
            if row.opportunity_type == "website_citation_readiness"
            or int((row.scope_snapshot or {}).get("batch_id") or 0) == batch_id
        ]
    if model_key:
        rows = [
            row for row in rows
            if row.opportunity_type != "website_citation_readiness"
            and model_key in ((row.scope_snapshot or {}).get("model_keys") or [])
        ]
    if question_plan_id is not None:
        rows = [
            row for row in rows
            if row.opportunity_type != "website_citation_readiness"
            and int((row.scope_snapshot or {}).get("question_plan_id") or 0)
            == question_plan_id
        ]
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
    is_website_action = opportunity.opportunity_type == "website_citation_readiness"
    selected_scope = {
        "opportunity_id": opportunity.id,
        "evidence_ids": [link.evidence_id for link in links],
        "question_plan_id": question_plan_id,
        "source_type": (opportunity.scope_snapshot or {}).get("source_type", "model_observation"),
    }
    if is_website_action:
        selected_scope.update(
            {
                "website_audit_id": opportunity.scope_snapshot.get("website_audit_id"),
                "raw_html_sha256": opportunity.scope_snapshot.get("raw_html_sha256"),
                "finding_codes": opportunity.scope_snapshot.get("finding_codes", []),
            }
        )
    action = GeoOptimizationAction(
        workspace_id=workspace_id,
        opportunity_id=opportunity.id,
        question_plan_id=question_plan_id,
        source_evidence_id=links[0].evidence_id if links else None,
        title=opportunity.title,
        rationale=opportunity.summary,
        hypothesis=(
            "补齐审计确认的服务端正文与页面结构后，重新审计应能验证官网可引用性改善。"
            if is_website_action
            else "补齐可引用、可复测的品牌答案后，目标问题中的品牌出现率应提升。"
        ),
        priority=opportunity.priority_label,
        status="proposed",
        stage="selected",
        baseline_snapshot=opportunity.scope_snapshot,
        selected_scope=selected_scope,
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
            detail={
                "opportunity_id": opportunity.id,
                "source_type": selected_scope["source_type"],
                "evidence_ids": selected_scope["evidence_ids"],
                "website_audit_id": selected_scope.get("website_audit_id"),
            },
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
    opportunity = db.get(GeoActionOpportunity, action.opportunity_id) if action.opportunity_id else None
    website_audit = None
    if opportunity and opportunity.opportunity_type == "website_citation_readiness":
        website_audit_id = int((opportunity.scope_snapshot or {}).get("website_audit_id") or 0)
        website_audit = db.get(GeoWebsiteAudit, website_audit_id) if website_audit_id else None
        if website_audit is None or website_audit.workspace_id != workspace_id:
            raise HTTPException(status_code=409, detail="Website audit evidence is no longer available")
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
    if website_audit:
        source_urls = list(
            dict.fromkeys(
                [*source_urls, website_audit.final_url or website_audit.requested_url]
            )
        )
    audience = payload.audience or ({"ciso": "安全与技术决策者", "procurement": "采购与业务负责人"}.get(question.role, "技术负责人") if question else "技术负责人")
    intent = payload.intent or (question.journey_stage if question else "consideration")
    required_sections = payload.required_sections or (
        ["首屏直接答案", "产品能力与边界", "适用场景", "验证方式", "常见问题", "来源"]
        if website_audit
        else ["问题背景", "可验证的解决方案", "证据与引用", "下一步行动"]
    )
    required_claims = [f"直接回答问题：{question.question_text}"] if question else [action.title]
    if website_audit:
        required_claims.extend(
            [
                "仅修复官网审计已确认的可读性与结构问题",
                "不得把官网审计得分表述为模型引用、品牌推荐或效果提升",
            ]
        )
    required_claims.append(f"所有关键事实均需引用已采集来源（{len(source_urls)} 个）")
    input_fingerprint = sha256(
        json.dumps(
            {
                "action_id": action.id,
                "audience": audience,
                "intent": intent,
                "sections": required_sections,
                "evidence_ids": evidence_ids,
                "website_audit_id": website_audit.id if website_audit else None,
                "website_audit_hash": website_audit.raw_html_sha256 if website_audit else None,
                "source_urls": source_urls,
            },
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
        status=(
            "ready"
            if (evidence_ids and source_urls)
            or (
                website_audit
                and website_audit.status != "blocked"
                and website_audit.raw_html_sha256
                and website_audit.artifact_manifest
            )
            else "blocked"
        ),
    )
    action.stage = "brief_ready" if brief.status == "ready" else "blocked"
    action.status = "in_progress"
    action.blocked_reason = (
        None
        if brief.status == "ready"
        else "No complete model observation or website audit artifact is attached"
    )
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
            detail={
                "brief_status": brief.status,
                "source_type": "website_audit" if website_audit else "model_observation",
                "evidence_ids": evidence_ids,
                "website_audit_id": website_audit.id if website_audit else None,
                "source_count": len(source_urls),
            },
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


def _normalized_fact_source(value: str | None) -> str:
    return str(value or "").strip().rstrip("/")


def _active_sourced_brand_facts(db: Session, workspace_id: int) -> list[GeoBrandFact]:
    return verified_active_brand_facts(db, workspace_id)


def _active_brand_facts_with_sources(db: Session, workspace_id: int) -> list[GeoBrandFact]:
    return list(
        db.scalars(
            select(GeoBrandFact)
            .where(
                GeoBrandFact.workspace_id == workspace_id,
                GeoBrandFact.status == "active",
                GeoBrandFact.source_url.is_not(None),
            )
            .order_by(GeoBrandFact.id)
        )
    )


REVIEW_RESOLVED_CLAIM_STATUSES = {
    "source_linked",
    "verified",
    "human_confirmed",
    "explicitly_unverified",
}


def _asset_sourced_brand_facts(
    db: Session,
    asset: GeoContentAsset,
    claims: list[GeoContentClaim] | None = None,
    active_facts: list[GeoBrandFact] | None = None,
) -> list[GeoBrandFact]:
    active_facts = (
        active_facts
        if active_facts is not None
        else _active_sourced_brand_facts(db, asset.workspace_id)
    )
    if not active_facts:
        return []
    asset_claims = claims if claims is not None else list(
        db.scalars(
            select(GeoContentClaim).where(GeoContentClaim.content_asset_id == asset.id)
        )
    )
    facts_by_id = {fact.id: fact for fact in active_facts}
    facts_by_value = {
        (fact.statement.strip(), _normalized_fact_source(fact.source_url)): fact
        for fact in active_facts
    }
    matched: dict[int, GeoBrandFact] = {}
    for claim in asset_claims:
        if claim.verification_status not in {"source_linked", "verified", "human_confirmed"}:
            continue
        fact = facts_by_id.get(int(claim.support_id or 0))
        if fact is not None and (
            fact.statement.strip() != claim.claim_text.strip()
            or _normalized_fact_source(fact.source_url)
            != _normalized_fact_source(claim.source_url)
        ):
            # A fact row can be edited after an asset was generated. Its ID alone
            # must never transfer a newer statement's proof onto an older claim.
            fact = None
        if fact is None:
            fact = facts_by_value.get(
                (claim.claim_text.strip(), _normalized_fact_source(claim.source_url))
            )
        if fact is not None:
            matched[fact.id] = fact
    return [matched[fact_id] for fact_id in sorted(matched)]


def _content_review_package(
    db: Session,
    asset: GeoContentAsset,
    *,
    active_sourced_brand_facts: list[GeoBrandFact] | None = None,
    active_brand_facts: list[GeoBrandFact] | None = None,
) -> dict:
    claims = list(
        db.scalars(
            select(GeoContentClaim)
            .where(GeoContentClaim.content_asset_id == asset.id)
            .order_by(GeoContentClaim.id)
        )
    )
    variants = list(
        db.scalars(
            select(GeoPlatformVariant)
            .where(GeoPlatformVariant.content_asset_id == asset.id)
            .order_by(GeoPlatformVariant.platform_key, GeoPlatformVariant.version.desc())
        )
    )
    reviews = list(
        db.scalars(
            select(GeoContentReview)
            .where(
                GeoContentReview.workspace_id == asset.workspace_id,
                (
                    (GeoContentReview.subject_type == "content_asset")
                    & (GeoContentReview.subject_id == asset.id)
                )
                | (
                    (GeoContentReview.subject_type == "platform_variant")
                    & (GeoContentReview.subject_id.in_([variant.id for variant in variants] or [-1]))
                ),
            )
            .order_by(GeoContentReview.id.desc())
        )
    )
    approved_variant_ids = {
        review.subject_id
        for review in reviews
        if review.subject_type == "platform_variant" and review.verdict == "approved"
    }
    approved_platform_keys = [
        variant.platform_key for variant in variants if variant.id in approved_variant_ids
    ]
    brief = db.get(GeoContentBrief, asset.brief_id)
    action = db.get(GeoOptimizationAction, brief.action_id) if brief else None
    opportunity = (
        db.get(GeoActionOpportunity, action.opportunity_id)
        if action is not None and action.opportunity_id
        else None
    )
    requires_sourced_brand_facts = _website_requires_sourced_brand_facts(opportunity)
    if active_sourced_brand_facts is None:
        active_sourced_brand_facts = _active_sourced_brand_facts(db, asset.workspace_id)
    if active_brand_facts is None:
        active_brand_facts = _active_brand_facts_with_sources(db, asset.workspace_id)
    verified_fact_ids = {fact.id for fact in active_sourced_brand_facts}
    unverified_brand_facts = [
        fact for fact in active_brand_facts if fact.id not in verified_fact_ids
    ]
    sourced_brand_facts = _asset_sourced_brand_facts(
        db,
        asset,
        claims,
        active_facts=active_sourced_brand_facts,
    )
    used_unverified_brand_facts = _asset_sourced_brand_facts(
        db,
        asset,
        claims,
        active_facts=unverified_brand_facts,
    )
    return {
        "asset": asset,
        "claims": claims,
        "variants": variants,
        "reviews": reviews,
        "pending_claim_count": sum(
            claim.verification_status not in REVIEW_RESOLVED_CLAIM_STATUSES
            for claim in claims
        ),
        "approved_platform_keys": list(dict.fromkeys(approved_platform_keys)),
        "requires_sourced_brand_facts": requires_sourced_brand_facts,
        "available_sourced_brand_fact_count": len(active_sourced_brand_facts),
        "sourced_brand_fact_count": len(sourced_brand_facts),
        "sourced_brand_fact_ids": [fact.id for fact in sourced_brand_facts],
        "unverified_brand_fact_count": len(unverified_brand_facts),
        "used_unverified_brand_fact_count": len(used_unverified_brand_facts),
    }


@router.get(
    "/workspaces/{workspace_id}/content-library",
    response_model=list[ContentLibraryItemRead],
)
def read_content_library(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    assets = list(
        db.scalars(
            select(GeoContentAsset)
            .where(GeoContentAsset.workspace_id == workspace_id)
            .order_by(GeoContentAsset.updated_at.desc(), GeoContentAsset.id.desc())
        )
    )
    if not assets:
        return []
    latest_asset_by_brief: dict[int, GeoContentAsset] = {}
    for candidate in sorted(assets, key=lambda item: (item.version, item.id), reverse=True):
        latest_asset_by_brief.setdefault(candidate.brief_id, candidate)
    briefs = {
        item.id: item
        for item in db.scalars(
            select(GeoContentBrief).where(
                GeoContentBrief.id.in_([asset.brief_id for asset in assets])
            )
        )
    }
    actions = {
        item.id: item
        for item in db.scalars(
            select(GeoOptimizationAction).where(
                GeoOptimizationAction.workspace_id == workspace_id,
                GeoOptimizationAction.id.in_([brief.action_id for brief in briefs.values()] or [-1]),
            )
        )
    }
    runs_by_asset: dict[int, GeoAgentRun] = {}
    for run in db.scalars(
        select(GeoAgentRun)
        .where(GeoAgentRun.workspace_id == workspace_id)
        .order_by(GeoAgentRun.id.desc())
    ):
        asset_id = int((run.result_snapshot or {}).get("asset_id") or 0)
        if asset_id:
            runs_by_asset.setdefault(asset_id, run)
    distributions_by_asset: dict[int, GeoDistributionRun] = {}
    for distribution in db.scalars(
        select(GeoDistributionRun)
        .where(GeoDistributionRun.workspace_id == workspace_id)
        .order_by(GeoDistributionRun.id.desc())
    ):
        if distribution.content_asset_id:
            distributions_by_asset.setdefault(distribution.content_asset_id, distribution)
    active_sourced_brand_facts = _active_sourced_brand_facts(db, workspace_id)
    active_brand_facts = _active_brand_facts_with_sources(db, workspace_id)

    items = []
    for asset in assets:
        brief = briefs.get(asset.brief_id)
        action = actions.get(brief.action_id) if brief else None
        if brief is None or action is None:
            continue
        package = _content_review_package(
            db,
            asset,
            active_sourced_brand_facts=active_sourced_brand_facts,
            active_brand_facts=active_brand_facts,
        )
        content_reviews = [
            review
            for review in package["reviews"]
            if review.subject_type == "content_asset" and review.subject_id == asset.id
        ]
        latest_review = content_reviews[0] if content_reviews else None
        latest_note = next(
            (
                str(issue.get("message") or "").strip()
                for issue in (latest_review.issues or [])
                if str(issue.get("message") or "").strip()
            ),
            None,
        ) if latest_review else None
        run = runs_by_asset.get(asset.id)
        latest_asset = latest_asset_by_brief[asset.brief_id]
        distribution = distributions_by_asset.get(asset.id)
        targets = list(
            db.scalars(
                select(GeoDistributionTarget).where(
                    GeoDistributionTarget.distribution_run_id == distribution.id
                )
            )
        ) if distribution else []
        items.append(
            {
                "asset": asset,
                "action_id": action.id,
                "action_title": action.title,
                "action_stage": action.stage,
                "question_plan_id": brief.question_plan_id,
                "variants": package["variants"],
                "pending_claim_count": package["pending_claim_count"],
                "available_sourced_brand_fact_count": package[
                    "available_sourced_brand_fact_count"
                ],
                "sourced_brand_fact_count": package["sourced_brand_fact_count"],
                "unverified_brand_fact_count": package[
                    "unverified_brand_fact_count"
                ],
                "used_unverified_brand_fact_count": package[
                    "used_unverified_brand_fact_count"
                ],
                "brand_fact_verification_required": (
                    package["requires_sourced_brand_facts"]
                    and package["sourced_brand_fact_count"] == 0
                    and package["unverified_brand_fact_count"] > 0
                ),
                "brand_fact_snapshot_stale": (
                    asset.id == latest_asset.id
                    and asset.status not in {"approved", "superseded"}
                    and package["available_sourced_brand_fact_count"] > 0
                    and package["sourced_brand_fact_count"] == 0
                ),
                "approved_platform_keys": package["approved_platform_keys"],
                "latest_review_verdict": latest_review.verdict if latest_review else None,
                "latest_review_note": latest_note,
                "agent_run_id": run.id if run else None,
                "agent_run_status": run.status if run else None,
                "distribution_run_id": distribution.id if distribution else None,
                "distribution_status": distribution.status if distribution else None,
                "saved_draft_count": sum(
                    target.draft_readback_status == "draft_saved" for target in targets
                ),
                "total_draft_targets": len(targets),
                "draft_targets": targets,
                "is_latest_version": asset.id == latest_asset.id,
                "latest_version_id": latest_asset.id,
                "latest_version_number": latest_asset.version,
            }
        )
    return items


@router.get(
    "/workspaces/{workspace_id}/content-assets/{asset_id}/review-package",
    response_model=ContentReviewPackageRead,
)
def read_content_review_package(
    workspace_id: int,
    asset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    asset = scoped_or_404(db, GeoContentAsset, workspace_id, asset_id)
    return _content_review_package(db, asset)


@router.post(
    "/workspaces/{workspace_id}/content-assets/{asset_id}/reviews",
    response_model=ContentReviewPackageRead,
    status_code=201,
)
def decide_content_review(
    workspace_id: int,
    asset_id: int,
    payload: ContentReviewDecision,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    asset = scoped_or_404(db, GeoContentAsset, workspace_id, asset_id)
    brief = scoped_or_404(db, GeoContentBrief, workspace_id, asset.brief_id)
    action = scoped_or_404(db, GeoOptimizationAction, workspace_id, brief.action_id)
    claims = list(
        db.scalars(
            select(GeoContentClaim).where(GeoContentClaim.content_asset_id == asset.id)
        )
    )
    variants = list(
        db.scalars(
            select(GeoPlatformVariant).where(GeoPlatformVariant.content_asset_id == asset.id)
        )
    )
    variants_by_key = {variant.platform_key: variant for variant in variants}
    if asset.status == "changes_requested":
        raise HTTPException(
            status_code=409,
            detail="This version was already rejected; generate a revised version before reviewing again",
        )
    if asset.status == "approved":
        raise HTTPException(status_code=409, detail="This content version was already approved")
    platform_keys = list(dict.fromkeys(payload.platform_keys))
    reviewed_platform_keys = list(dict.fromkeys(payload.reviewed_platform_keys))
    missing_platforms = [key for key in platform_keys if key not in variants_by_key]
    if missing_platforms:
        raise HTTPException(status_code=422, detail=f"Platform variants not found: {', '.join(missing_platforms)}")
    invalid_reviewed_platforms = [key for key in reviewed_platform_keys if key not in variants_by_key]
    if invalid_reviewed_platforms:
        raise HTTPException(
            status_code=422,
            detail=f"已查看的平台稿不存在：{', '.join(invalid_reviewed_platforms)}",
        )
    if payload.verdict == "approved" and not platform_keys:
        raise HTTPException(status_code=422, detail="Select at least one platform variant to approve")
    unreviewed_platforms = [key for key in platform_keys if key not in reviewed_platform_keys]
    if payload.verdict == "approved" and unreviewed_platforms:
        raise HTTPException(
            status_code=422,
            detail=f"请先打开并审阅这些平台稿，再批准：{', '.join(unreviewed_platforms)}",
        )
    opportunity = db.get(GeoActionOpportunity, action.opportunity_id) if action.opportunity_id else None
    active_sourced_brand_facts = _active_sourced_brand_facts(db, workspace_id)
    asset_sourced_brand_facts = _asset_sourced_brand_facts(
        db,
        asset,
        claims,
        active_facts=active_sourced_brand_facts,
    )
    if (
        payload.verdict == "approved"
        and "official_site" in platform_keys
        and opportunity is not None
        and opportunity.opportunity_type == "website_citation_readiness"
        and _website_requires_sourced_brand_facts(opportunity)
    ):
        if not asset_sourced_brand_facts:
            raise HTTPException(
                status_code=409,
                detail=(
                    "这版官网稿生成时没有使用带公开来源的品牌事实；"
                    "请先补齐品牌事实并退回生成新版本，不能把通用整改框架批准为官网成稿"
                ),
            )
    if (
        payload.verdict == "approved"
        and active_sourced_brand_facts
        and not asset_sourced_brand_facts
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "当前工作区已有带公开来源的品牌事实，但这版稿件未使用任何一条；"
                "请退回并生成新版本，避免批准过时的待补证内容"
            ),
        )

    unresolved = [
        claim
        for claim in claims
        if claim.verification_status not in REVIEW_RESOLVED_CLAIM_STATUSES
    ]
    confirmed_ids = set(payload.confirmed_claim_ids)
    unverified_ids = set(payload.unverified_claim_ids)
    unresolved_ids = {claim.id for claim in unresolved}
    if payload.verdict == "approved" and confirmed_ids & unverified_ids:
        raise HTTPException(
            status_code=422,
            detail="A claim cannot be both confirmed and kept unverified",
        )
    reviewed_ids = confirmed_ids | unverified_ids
    invalid_ids = reviewed_ids - unresolved_ids
    if payload.verdict == "approved" and invalid_ids:
        raise HTTPException(
            status_code=422,
            detail=f"Claim decisions must target unresolved claims: {', '.join(map(str, sorted(invalid_ids)))}",
        )
    if payload.verdict == "approved" and not unresolved_ids.issubset(reviewed_ids):
        remaining = len(unresolved_ids - reviewed_ids)
        raise HTTPException(
            status_code=422,
            detail=f"{remaining} unsupported claims still require an explicit review decision",
        )

    note = (payload.note or "").strip()
    if payload.verdict == "changes_requested" and not note:
        raise HTTPException(status_code=422, detail="Explain what must change before sending the draft back")

    if payload.verdict == "approved":
        for claim in unresolved:
            if claim.id in confirmed_ids:
                claim.verification_status = "human_confirmed"
                claim.review_note = note or "人工审核时明确确认"
            elif claim.id in unverified_ids:
                claim.verification_status = "explicitly_unverified"
                claim.review_note = "人工审核明确保留为未核验；所选稿件不得将其作为已证实事实"
        asset.status = "approved"
    else:
        asset.status = "changes_requested"

    issue = {"code": "review_note", "message": note} if note else None
    db.add(
        GeoContentReview(
            workspace_id=workspace_id,
            subject_type="content_asset",
            subject_id=asset.id,
            review_type="human",
            verdict=payload.verdict,
            checks={
                "claim_count": len(claims),
                "confirmed_claim_ids": sorted(confirmed_ids & unresolved_ids),
                "unverified_claim_ids": sorted(unverified_ids & unresolved_ids),
                "platform_keys": platform_keys,
                "reviewed_platform_keys": reviewed_platform_keys,
            },
            issues=[issue] if issue else [],
            reviewer_id=user.id,
        )
    )
    for platform_key in platform_keys:
        variant = variants_by_key[platform_key]
        variant.status = payload.verdict
        db.add(
            GeoContentReview(
                workspace_id=workspace_id,
                subject_type="platform_variant",
                subject_id=variant.id,
                review_type="human",
                verdict=payload.verdict,
                checks={
                    "platform_key": platform_key,
                    "content_fingerprint": variant.content_fingerprint,
                    "reviewed_before_approval": platform_key in reviewed_platform_keys,
                },
                issues=[issue] if issue else [],
                reviewer_id=user.id,
            )
        )
    previous_stage = action.stage
    action.stage = "reviewing"
    action.blocked_reason = note if payload.verdict == "changes_requested" else None
    db.add(
        GeoActionEvent(
            workspace_id=workspace_id,
            action_id=action.id,
            event_type="content_review_decided",
            from_stage=previous_stage,
            to_stage="reviewing",
            actor_type="user",
            actor_user_id=user.id,
            detail={
                "asset_id": asset.id,
                "verdict": payload.verdict,
                "platform_keys": platform_keys,
                "confirmed_claim_count": len(confirmed_ids & unresolved_ids),
                "unverified_claim_count": len(unverified_ids & unresolved_ids),
            },
        )
    )
    db.commit()
    db.refresh(asset)
    return _content_review_package(db, asset)


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


@router.get(
    "/workspaces/{workspace_id}/distribution-runs",
    response_model=list[DistributionRunRead],
)
def list_distribution_runs(
    workspace_id: int,
    action_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    statement = select(GeoDistributionRun).where(GeoDistributionRun.workspace_id == workspace_id)
    if action_id is not None:
        statement = statement.where(GeoDistributionRun.action_id == action_id)
    runs = list(db.scalars(statement.order_by(GeoDistributionRun.id.desc())))
    return [_distribution_read(db, run) for run in runs]


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
    if asset.status != "approved":
        raise HTTPException(status_code=409, detail="Content asset must pass human review before sync")
    platform_keys = list(dict.fromkeys(payload.platform_keys))
    if "official_site" in platform_keys and platform_keys != ["official_site"]:
        raise HTTPException(status_code=422, detail="官网人工交付必须建立独立任务")
    is_website_handoff = platform_keys == ["official_site"]
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
                GeoPlatformVariant.platform_key.in_(platform_keys),
                GeoPlatformVariant.version == 1,
            )
        )
    }
    unavailable = [
        platform_key
        for platform_key in platform_keys
        if platform_key not in variants or variants[platform_key].status != "approved"
    ]
    if unavailable:
        raise HTTPException(
            status_code=409,
            detail=f"Platform variants require human approval: {', '.join(unavailable)}",
        )
    existing_client_run = None
    if not is_website_handoff:
        existing_client_run = db.scalar(
            select(GeoDistributionRun)
            .join(
                GeoDistributionTarget,
                GeoDistributionTarget.distribution_run_id == GeoDistributionRun.id,
            )
            .where(
                GeoDistributionRun.workspace_id == workspace_id,
                GeoDistributionRun.content_asset_id == asset.id,
                GeoDistributionTarget.adapter_version == "browser-extension.v1",
            )
            .order_by(GeoDistributionRun.id.desc())
        )
    if existing_client_run is not None:
        existing_targets = list(
            db.scalars(
                select(GeoDistributionTarget)
                .where(GeoDistributionTarget.distribution_run_id == existing_client_run.id)
                .order_by(GeoDistributionTarget.id)
            )
        )
        existing_platform_keys = {target.platform_key for target in existing_targets}
        missing_platform_keys = [
            platform_key for platform_key in platform_keys if platform_key not in existing_platform_keys
        ]
        if not missing_platform_keys:
            return _distribution_read(db, existing_client_run)
        for platform_key in missing_platform_keys:
            variant = variants[platform_key]
            db.add(
                GeoDistributionTarget(
                    distribution_run_id=existing_client_run.id,
                    platform_variant_id=variant.id,
                    platform_key=platform_key,
                    adapter_version="browser-extension.v1",
                    request_status="not_started",
                    draft_readback_status="not_started",
                    human_publish_status="not_ready",
                    waiting_human_reason="等待用户在当前浏览器中打开文章同步助手并确认写入。",
                )
            )
        existing_client_run.requested_platforms = list(
            dict.fromkeys([*(existing_client_run.requested_platforms or []), *platform_keys])
        )
        saved_count = sum(
            target.draft_readback_status == "draft_saved" for target in existing_targets
        )
        failed_count = sum(target.request_status == "failed" for target in existing_targets)
        existing_client_run.status = "partial" if saved_count or failed_count else "pending"
        existing_client_run.stage = (
            "needs_attention"
            if failed_count
            else "awaiting_client_results"
            if saved_count
            else "ready_for_client"
        )
        if action:
            previous_stage = action.stage
            action.stage = "sync_requested"
            action.blocked_reason = None
            db.add(
                GeoActionEvent(
                    workspace_id=workspace_id,
                    action_id=action.id,
                    event_type="distribution_targets_extended",
                    from_stage=previous_stage,
                    to_stage="sync_requested",
                    actor_type="user",
                    actor_user_id=user.id,
                    detail={
                        "distribution_run_id": existing_client_run.id,
                        "added_platform_keys": missing_platform_keys,
                        "requested_platform_keys": existing_client_run.requested_platforms,
                        "final_action_clicked": False,
                    },
                )
            )
        db.commit()
        db.refresh(existing_client_run)
        return _distribution_read(db, existing_client_run)
    run = GeoDistributionRun(
        workspace_id=workspace_id,
        action_id=action.id if action else None,
        content_asset_id=asset.id,
        requested_platforms=platform_keys,
        stage="awaiting_publication" if is_website_handoff else "ready_for_client",
        idempotency_key=payload.idempotency_key,
        status="awaiting_publication" if is_website_handoff else "pending",
        requested_by_user_id=user.id,
    )
    db.add(run)
    db.flush()
    for platform_key in platform_keys:
        variant = variants.get(platform_key)
        db.add(
            GeoDistributionTarget(
                distribution_run_id=run.id,
                platform_variant_id=variant.id if variant else None,
                platform_key=platform_key,
                adapter_version="manual-website.v1" if is_website_handoff else "browser-extension.v1",
                request_status="handoff_ready" if is_website_handoff else "not_started",
                draft_readback_status="not_required" if is_website_handoff else "not_started",
                human_publish_status="awaiting_publish" if is_website_handoff else "not_ready",
                waiting_human_reason=(
                    "官网稿已通过审核并建立交付记录；等待网站负责人部署后回填公开 URL。"
                    if is_website_handoff
                    else "等待用户在当前浏览器中打开文章同步助手并确认写入。"
                ),
            )
        )
    if action:
        previous_stage = action.stage
        action.stage = "awaiting_publication" if is_website_handoff else "sync_requested"
        action.blocked_reason = None
        db.add(
            GeoActionEvent(
                workspace_id=workspace_id,
                action_id=action.id,
                event_type=(
                    "website_handoff_created"
                    if is_website_handoff
                    else "distribution_ready_for_client"
                ),
                from_stage=previous_stage,
                to_stage=action.stage,
                actor_type="user",
                actor_user_id=user.id,
                detail={
                    "distribution_run_id": run.id,
                    "platform_keys": platform_keys,
                    "delivery_mode": "manual_website" if is_website_handoff else "browser_extension",
                    "final_action_clicked": False,
                },
            )
        )
    db.commit()
    db.refresh(run)
    return _distribution_read(db, run)


@router.post(
    "/workspaces/{workspace_id}/distribution-runs/{run_id}/client-results",
    response_model=DistributionRunRead,
)
def record_distribution_client_results(
    workspace_id: int,
    run_id: int,
    payload: DistributionClientResults,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    run = scoped_or_404(db, GeoDistributionRun, workspace_id, run_id)
    targets = list(
        db.scalars(
            select(GeoDistributionTarget)
            .where(GeoDistributionTarget.distribution_run_id == run.id)
            .order_by(GeoDistributionTarget.id)
        )
    )
    by_platform = {target.platform_key: target for target in targets}
    seen: set[str] = set()
    for result in payload.targets:
        if result.platform_key in seen:
            raise HTTPException(status_code=422, detail=f"Duplicate platform result: {result.platform_key}")
        seen.add(result.platform_key)
        target = by_platform.get(result.platform_key)
        if target is None:
            raise HTTPException(status_code=422, detail=f"Platform is not part of this sync run: {result.platform_key}")
        if target.adapter_version == "manual-website.v1":
            raise HTTPException(status_code=409, detail="官网人工交付不接受文章同步助手草稿结果")
        if result.request_status == "draft_link_returned":
            if not result.draft_url:
                raise HTTPException(
                    status_code=422,
                    detail=f"{result.platform_key} requires the returned draft URL",
                )
            candidate_draft_url = _validated_draft_url(result.platform_key, result.draft_url)
            target.request_status = "draft_link_returned"
            target.draft_readback_status = "awaiting_human_confirmation"
            target.candidate_draft_url = candidate_draft_url
            target.draft_url = None
            target.external_draft_id = result.external_draft_id
            target.waiting_human_reason = "同步助手已返回草稿地址；请打开并确认草稿真实可见。"
            target.blocked_reason = None
            target.last_error_code = None
            target.human_publish_status = "not_ready"
            target.publication_verification_status = "not_checked"
        elif result.request_status == "draft_saved":
            if not result.draft_url and not result.external_draft_id:
                raise HTTPException(
                    status_code=422,
                    detail=f"{result.platform_key} requires a draft URL or external draft ID",
                )
            verified_draft_url = (
                _validated_draft_url(result.platform_key, result.draft_url)
                if result.draft_url
                else None
            )
            target.request_status = "draft_saved"
            target.draft_readback_status = "draft_saved"
            target.candidate_draft_url = verified_draft_url
            target.draft_url = verified_draft_url
            target.external_draft_id = result.external_draft_id
            target.waiting_human_reason = "平台草稿已回读；最终发布仍等待人工确认。"
            target.blocked_reason = None
            target.last_error_code = None
            if target.human_publish_status != "published":
                target.human_publish_status = "awaiting_publish"
                target.publication_verification_status = "not_checked"
        elif result.request_status == "failed":
            target.request_status = "failed"
            target.draft_readback_status = "failed"
            target.candidate_draft_url = None
            target.draft_url = None
            target.external_draft_id = None
            target.blocked_reason = (result.message or "文章同步助手未能保存草稿")[:2000]
            target.last_error_code = "client_sync_failed"
            target.waiting_human_reason = None
        else:
            target.request_status = "cancelled"
            target.draft_readback_status = "not_started"
            target.candidate_draft_url = None
            target.draft_url = None
            target.external_draft_id = None
            target.waiting_human_reason = result.message or "用户取消了本次平台草稿写入。"
        target.final_action_clicked = False

    saved_count = sum(target.draft_readback_status == "draft_saved" for target in targets)
    failed_count = sum(target.request_status == "failed" for target in targets)
    awaiting_confirmation_count = sum(
        target.draft_readback_status == "awaiting_human_confirmation" for target in targets
    )
    pending_count = len(targets) - saved_count - failed_count
    if saved_count == len(targets):
        run.stage = "draft_saved"
        run.status = "draft_saved"
    elif failed_count and not saved_count and pending_count == 0:
        run.stage = "needs_attention"
        run.status = "failed"
    elif awaiting_confirmation_count:
        run.stage = "awaiting_readback"
        run.status = "pending"
    else:
        run.stage = "needs_attention" if failed_count else "awaiting_client_results"
        run.status = "partial" if saved_count or failed_count else "pending"
    action = db.get(GeoOptimizationAction, run.action_id) if run.action_id else None
    if action:
        # A saved draft is not a published result and never advances the action
        # to verified. Verification requires a later real re-observation.
        action.stage = "awaiting_publication" if saved_count == len(targets) else "awaiting_readback"
        action.blocked_reason = None if not failed_count else "部分平台草稿写入失败，请核对逐平台结果。"
    db.add(
        GeoActionEvent(
            workspace_id=workspace_id,
            action_id=run.action_id,
            event_type="distribution_client_results_recorded",
            from_stage="sync_requested",
            to_stage=action.stage if action else run.stage,
            actor_type="user",
            actor_user_id=user.id,
            detail={
                "distribution_run_id": run.id,
                "saved_count": saved_count,
                "failed_count": failed_count,
                "awaiting_confirmation_count": awaiting_confirmation_count,
                "pending_count": pending_count,
                "final_action_clicked": False,
            },
        )
    )
    db.commit()
    db.refresh(run)
    return _distribution_read(db, run)


def _validated_draft_url(platform_key: str, value: str) -> str:
    url = value.strip()
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="草稿地址必须是完整的 HTTPS URL")

    expected_domains = {
        "zhihu": "zhihu.com",
        "juejin": "juejin.cn",
        "csdn": "csdn.net",
        "51cto": "51cto.com",
        "wechat": "mp.weixin.qq.com",
    }
    expected = expected_domains.get(platform_key)
    valid = expected is not None and (host == expected or host.endswith(f".{expected}"))
    if not valid or not parsed.path or parsed.path == "/":
        raise HTTPException(status_code=422, detail="同步助手返回的地址不是当前平台草稿页")
    return parsed.geturl()


@router.post(
    "/workspaces/{workspace_id}/distribution-runs/{run_id}/targets/{target_id}/human-draft-readback",
    response_model=DistributionRunRead,
)
def confirm_human_draft_readback(
    workspace_id: int,
    run_id: int,
    target_id: int,
    payload: HumanDraftReadbackRecord,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    run = scoped_or_404(db, GeoDistributionRun, workspace_id, run_id)
    targets = list(
        db.scalars(
            select(GeoDistributionTarget)
            .where(GeoDistributionTarget.distribution_run_id == run.id)
            .order_by(GeoDistributionTarget.id)
        )
    )
    target = next((item for item in targets if item.id == target_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Distribution target not found")
    if target.adapter_version == "manual-website.v1":
        raise HTTPException(status_code=409, detail="官网人工交付不使用平台草稿回读")
    if target.draft_readback_status == "draft_saved":
        return _distribution_read(db, run)
    if (
        target.request_status != "draft_link_returned"
        or target.draft_readback_status != "awaiting_human_confirmation"
        or not target.candidate_draft_url
    ):
        raise HTTPException(status_code=409, detail="当前目标没有等待确认的草稿地址")

    draft_url = _validated_draft_url(target.platform_key, target.candidate_draft_url)
    previous_stage = run.stage
    target.draft_url = draft_url
    target.request_status = "draft_saved"
    target.draft_readback_status = "draft_saved"
    target.readback_artifact_uri = f"human://draft-readback/{run.id}/{target.id}"
    target.waiting_human_reason = None
    target.blocked_reason = None
    target.last_error_code = None
    target.human_publish_status = "awaiting_publish"
    target.publication_verification_status = "not_checked"
    target.final_action_clicked = False
    all_saved = all(item.draft_readback_status == "draft_saved" for item in targets)
    run.stage = "draft_saved" if all_saved else "awaiting_readback"
    run.status = "draft_saved" if all_saved else "pending"
    action = db.get(GeoOptimizationAction, run.action_id) if run.action_id else None
    if action:
        action.stage = "awaiting_publication" if all_saved else "awaiting_readback"
        action.blocked_reason = None
    db.add(
        GeoActionEvent(
            workspace_id=workspace_id,
            action_id=run.action_id,
            event_type="draft_readback_human_confirmed",
            from_stage=previous_stage,
            to_stage=run.stage,
            actor_type="user",
            actor_user_id=user.id,
            detail={
                "distribution_run_id": run.id,
                "target_id": target.id,
                "platform_key": target.platform_key,
                "confirmed_visible": payload.confirmed_visible,
                "final_action_clicked": False,
            },
        )
    )
    db.commit()
    db.refresh(run)
    return _distribution_read(db, run)


def _validated_publication_url(
    workspace: GeoWorkspace,
    platform_key: str,
    value: str,
) -> str:
    url = value.strip()
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="公开文章地址必须是完整的 HTTPS URL")
    def host_matches(expected: str) -> bool:
        return host == expected or host.endswith(f".{expected}")

    if platform_key == "zhihu":
        valid = host_matches("zhihu.com")
        expected_label = "知乎"
    elif platform_key == "juejin":
        valid = host_matches("juejin.cn")
        expected_label = "稀土掘金"
    elif platform_key == "csdn":
        valid = host_matches("csdn.net")
        expected_label = "CSDN"
    elif platform_key == "51cto":
        valid = host_matches("51cto.com")
        expected_label = "51CTO"
    elif platform_key == "wechat":
        valid = host == "mp.weixin.qq.com"
        expected_label = "微信公众号"
    elif platform_key == "xiaohongshu":
        valid = host_matches("xiaohongshu.com")
        expected_label = "小红书"
    elif platform_key == "official_site":
        website_host = (urlsplit(workspace.website_url or "").hostname or "").lower().rstrip(".")
        if not website_host:
            raise HTTPException(status_code=422, detail="请先在设置中配置官网域名")
        valid = host == website_host or host.endswith(f".{website_host}")
        expected_label = "当前工作区官网"
    else:
        raise HTTPException(status_code=422, detail="当前平台尚不支持发布结果归档")
    if not valid:
        raise HTTPException(status_code=422, detail=f"该地址不是{expected_label}的公开文章 URL")
    if platform_key != "official_site" and (not parsed.path or parsed.path == "/"):
        raise HTTPException(status_code=422, detail="请填写具体文章页面，而不是平台首页")
    return parsed.geturl()


@router.post(
    "/workspaces/{workspace_id}/distribution-runs/{run_id}/targets/{target_id}/human-publication",
    response_model=DistributionRunRead,
)
def record_human_publication(
    workspace_id: int,
    run_id: int,
    target_id: int,
    payload: HumanPublicationRecord,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace = workspace_or_404(db, user, workspace_id)
    run = scoped_or_404(db, GeoDistributionRun, workspace_id, run_id)
    target = db.get(GeoDistributionTarget, target_id)
    if target is None or target.distribution_run_id != run.id:
        raise HTTPException(status_code=404, detail="发布目标不存在")
    is_manual_website_handoff = (
        target.platform_key == "official_site"
        and target.adapter_version == "manual-website.v1"
        and target.request_status == "handoff_ready"
        and target.draft_readback_status == "not_required"
    )
    if is_manual_website_handoff:
        asset = db.get(GeoContentAsset, run.content_asset_id) if run.content_asset_id else None
        variant = db.get(GeoPlatformVariant, target.platform_variant_id) if target.platform_variant_id else None
        if (
            asset is None
            or asset.workspace_id != workspace_id
            or asset.status != "approved"
            or variant is None
            or variant.content_asset_id != asset.id
            or variant.status != "approved"
        ):
            raise HTTPException(status_code=409, detail="官网稿必须保持人工审核通过后才能记录上线")
    elif target.draft_readback_status != "draft_saved":
        raise HTTPException(status_code=409, detail="只有已回读的真实平台草稿可以记录发布结果")
    public_url = _validated_publication_url(workspace, target.platform_key, payload.public_url)
    if (
        target.human_publish_status == "published"
        and target.public_url == public_url
        and target.publication_verification_status == "publicly_verified"
    ):
        return _distribution_read(db, run)
    retest = db.scalar(
        select(GeoReobservation).where(
            GeoReobservation.action_id == run.action_id,
            GeoReobservation.retest_batch_id.is_not(None),
        )
    ) if run.action_id else None
    if target.public_url and target.public_url != public_url and retest is not None:
        raise HTTPException(
            status_code=409,
            detail="同口径复测已建立，发布 URL 已锁定；如需更正，请保留本次记录并创建新的发布行动",
        )
    previous_url = target.public_url
    try:
        verification = verify_publication_page(public_url)
        _validated_publication_url(
            workspace,
            target.platform_key,
            str(verification.get("verified_url") or ""),
        )
    except WebsiteAuditTargetError as exc:
        raise HTTPException(
            status_code=422,
            detail="公开页面地址未通过公网安全校验，请确认它不是内网或本机地址",
        ) from exc
    except PublicationVerificationError as exc:
        raise HTTPException(
            status_code=409,
            detail="暂时无法从公网读取该 HTML 页面；本次不会记录为已上线或已发布",
        ) from exc
    except HTTPException:
        raise
    now = datetime.now(timezone.utc)
    target.human_publish_status = "published"
    target.public_url = public_url
    target.publication_verification_status = "publicly_verified"
    target.published_at = now
    target.published_by_user_id = user.id
    target.waiting_human_reason = None
    # The product records the user's platform action; it never claims that our
    # system clicked the final publish control.
    target.final_action_clicked = False

    targets = list(
        db.scalars(
            select(GeoDistributionTarget)
            .where(GeoDistributionTarget.distribution_run_id == run.id)
            .order_by(GeoDistributionTarget.id)
        )
    )
    all_published = bool(targets) and all(
        item.human_publish_status == "published"
        and item.public_url
        and item.publication_verification_status == "publicly_verified"
        for item in targets
    )
    run.stage = "published" if all_published else "awaiting_publication"
    run.status = "published" if all_published else "partial"
    action = db.get(GeoOptimizationAction, run.action_id) if run.action_id else None
    previous_stage = action.stage if action else run.stage
    if action:
        action.stage = "ready_for_retest" if all_published else "awaiting_publication"
        action.blocked_reason = None
    db.add(
        GeoActionEvent(
            workspace_id=workspace_id,
            action_id=run.action_id,
            event_type="human_publication_recorded",
            from_stage=previous_stage,
            to_stage=action.stage if action else run.stage,
            actor_type="user",
            actor_user_id=user.id,
            detail={
                "distribution_run_id": run.id,
                "target_id": target.id,
                "platform_key": target.platform_key,
                "public_url": public_url,
                "corrected": bool(previous_url and previous_url != public_url),
                "all_targets_published": all_published,
                "final_action_clicked": False,
                "publication_verification": verification,
            },
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


ACTIVE_AGENT_RUN_STATUSES = ("queued", "resuming", "running", "cancelling")


def _agent_capacity(
    db: Session,
    workspace_id: int,
    *,
    exclude_run_id: int | None = None,
) -> tuple[int, list[GeoAgentRun]]:
    limit = max(1, min(int(get_settings().agent_max_concurrent_runs), 4))
    query = select(GeoAgentRun).where(
        GeoAgentRun.workspace_id == workspace_id,
        GeoAgentRun.status.in_(ACTIVE_AGENT_RUN_STATUSES),
    )
    if exclude_run_id is not None:
        query = query.where(GeoAgentRun.id != exclude_run_id)
    active_runs = list(db.scalars(query.order_by(GeoAgentRun.id.desc())))
    return limit, active_runs


def _agent_runtime_diagnostic(db: Session, workspace_id: int) -> dict:
    diagnostic = diagnose_local_codex()
    limit, active_runs = _agent_capacity(db, workspace_id)
    return {
        **diagnostic,
        "active_run_count": len(active_runs),
        "max_concurrent_runs": limit,
        "capacity_available": len(active_runs) < limit,
        "run_timeout_seconds": max(
            60,
            min(int(get_settings().agent_run_timeout_seconds), 3600),
        ),
    }


def _assert_agent_capacity(
    db: Session,
    workspace_id: int,
    *,
    exclude_run_id: int | None = None,
) -> None:
    limit, active_runs = _agent_capacity(db, workspace_id, exclude_run_id=exclude_run_id)
    if len(active_runs) < limit:
        return
    busy = active_runs[0]
    raise HTTPException(
        status_code=409,
        detail=(
            f"Workspace Agent capacity is busy ({len(active_runs)}/{limit}) with run {busy.id}; "
            "wait for it to finish or interrupt it before starting another run"
        ),
    )


@router.get(
    "/workspaces/{workspace_id}/agent-runtime",
    response_model=AgentRuntimeRead,
)
def read_agent_runtime(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    return _agent_runtime_diagnostic(db, workspace_id)


@router.post(
    "/workspaces/{workspace_id}/agent-runtime/test",
    response_model=AgentRuntimeTestRead,
)
def test_agent_runtime(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    invalidate_local_codex_diagnostic_cache()
    diagnostic = _agent_runtime_diagnostic(db, workspace_id)
    started = perf_counter()
    if not diagnostic.get("ready"):
        return {
            "ok": False,
            "runtime": diagnostic,
            "latency_ms": int((perf_counter() - started) * 1000),
            "error": diagnostic.get("error") or "Codex login is required",
        }
    if not diagnostic.get("capacity_available"):
        return {
            "ok": False,
            "runtime": diagnostic,
            "latency_ms": int((perf_counter() - started) * 1000),
            "error": "Codex Agent 当前容量已满，请等待正在运行的任务结束",
        }
    import tempfile

    try:
        with tempfile.TemporaryDirectory(prefix="cqyq-codex-runtime-test-") as directory:
            result = LocalCodexRuntime().run_structured(
                task_directory=Path(directory),
                prompt="Return JSON confirming that this local Codex runtime can complete a structured turn.",
                output_schema={
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                    "additionalProperties": False,
                },
                developer_instructions="Do not read or write files. Return only the requested JSON.",
                model=diagnostic.get("default_model"),
            )
        parsed = json.loads(result.final_response)
        return {
            "ok": parsed.get("ok") is True,
            "runtime": diagnostic,
            "latency_ms": int((perf_counter() - started) * 1000),
            "thread_id": result.thread_id,
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "runtime": diagnostic,
            "latency_ms": int((perf_counter() - started) * 1000),
            "error": str(exc)[:500],
        }


def _default_agent_platforms(db: Session, action: GeoOptimizationAction) -> list[str]:
    opportunity = db.get(GeoActionOpportunity, action.opportunity_id) if action.opportunity_id else None
    requested = list(opportunity.recommended_platforms or []) if opportunity else []
    supported = [
        key
        for key in requested
        if key
        in {"zhihu", "juejin", "csdn", "51cto", "wechat", "official_site", "xiaohongshu"}
    ]
    preferred = [key for key in supported if key != "official_site"]
    return (preferred or supported or ["zhihu", "juejin"])[:2]


def _website_requires_sourced_brand_facts(opportunity: GeoActionOpportunity | None) -> bool:
    if opportunity is None or opportunity.opportunity_type != "website_citation_readiness":
        return False
    finding_codes = {
        str(code)
        for code in (opportunity.scope_snapshot or {}).get("finding_codes", [])
        if str(code)
    }
    return bool(
        finding_codes
        & {
            "client_rendering_required",
            "server_visible_content_missing",
            "server_visible_content_too_short",
        }
    )


@router.post(
    "/workspaces/{workspace_id}/actions/{action_id}/agent-runs",
    response_model=AgentRunRead,
    status_code=202,
)
def create_agent_run(
    workspace_id: int,
    action_id: int,
    payload: AgentRunCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    action = scoped_or_404(db, GeoOptimizationAction, workspace_id, action_id)
    opportunity = db.get(GeoActionOpportunity, action.opportunity_id) if action.opportunity_id else None
    if opportunity is None or opportunity.workspace_id != workspace_id:
        raise HTTPException(
            status_code=409,
            detail="当前行动未关联已持久化的真实机会，请重新选择当前机会后再启动 Agent。",
        )
    website_audit = None
    if opportunity and opportunity.opportunity_type == "website_citation_readiness":
        website_audit_id = int((opportunity.scope_snapshot or {}).get("website_audit_id") or 0)
        website_audit = db.get(GeoWebsiteAudit, website_audit_id) if website_audit_id else None
        if website_audit is None or website_audit.workspace_id != workspace_id:
            raise HTTPException(status_code=409, detail="Website audit evidence is no longer available")
        if (
            website_audit.status == "blocked"
            or not website_audit.raw_html_sha256
            or not website_audit.artifact_manifest
        ):
            raise HTTPException(
                status_code=409,
                detail="Website audit is incomplete; resolve access and run the audit again before drafting",
            )
    else:
        if action.question_plan_id is None:
            raise HTTPException(
                status_code=409,
                detail="当前机会已缺少目标问题，请按最新观测范围重新发现机会后再生成。",
            )
        evidence_ids, _source_urls = action_evidence_inputs(db, action, opportunity)
        if not evidence_ids:
            raise HTTPException(
                status_code=409,
                detail=(
                    "当前机会没有完整的真实观测证据。生成前必须同时具备最终回答、"
                    "已验证搜索事件、公开来源 URL 和原始工件。"
                ),
            )
    invalidate_local_codex_diagnostic_cache()
    diagnostic = diagnose_local_codex()
    if not diagnostic.get("ready"):
        raise HTTPException(
            status_code=409,
            detail=diagnostic.get("error") or "Local Codex Agent is not ready; sign in with ChatGPT first",
        )
    active = db.scalar(
        select(GeoAgentRun)
        .where(
            GeoAgentRun.workspace_id == workspace_id,
            GeoAgentRun.action_id == action_id,
            GeoAgentRun.status.in_(ACTIVE_AGENT_RUN_STATUSES),
        )
        .order_by(GeoAgentRun.id.desc())
    )
    if active:
        raise HTTPException(status_code=409, detail=f"Agent run {active.id} is already active")
    _assert_agent_capacity(db, workspace_id)
    platforms = list(dict.fromkeys(payload.selected_platforms or _default_agent_platforms(db, action)))
    if not platforms:
        raise HTTPException(status_code=422, detail="Select at least one target platform")
    if website_audit and platforms != ["official_site"]:
        raise HTTPException(
            status_code=422,
            detail="Website audit actions must generate the official-site draft before external distribution",
        )
    if website_audit:
        readable_brand_source_missing = _website_requires_sourced_brand_facts(opportunity)
        sourced_brand_fact_count = len(verified_active_brand_facts(db, workspace_id))
        if readable_brand_source_missing and sourced_brand_fact_count == 0:
            raise HTTPException(
                status_code=409,
                detail=(
                    "官网没有可回读的产品正文，品牌事实库也没有通过公网与原文核验的可用事实；"
                    "请先在设置中核验品牌事实，避免只生成通用整改框架"
                ),
            )
    model = payload.model or diagnostic.get("default_model")
    if model and model not in diagnostic.get("available_models", []):
        raise HTTPException(status_code=422, detail="Selected Codex model is not available locally")
    run = GeoAgentRun(
        workspace_id=workspace_id,
        action_id=action_id,
        requested_by_user_id=user.id,
        runtime_key="local_codex",
        model=model,
        status="queued",
        stage="queued",
        selected_platforms=platforms,
        request_snapshot={"action_id": action_id, "selected_platforms": platforms},
    )
    db.add(run)
    db.flush()
    job = QueueJob(
        job_type="geo_agent.run",
        status="pending",
        priority=20,
        scheduled_at=datetime.now(timezone.utc),
        max_attempts=1,
        payload_json={
            "project_id": 0,
            "workspace_id": workspace_id,
            "action_id": action_id,
            "agent_run_id": run.id,
            "actor_user_id": user.id,
        },
    )
    db.add(job)
    db.flush()
    run.job_id = job.id
    previous_stage = action.stage
    action.stage = "generating"
    action.status = "in_progress"
    action.blocked_reason = None
    db.commit()
    append_agent_event(
        db,
        run,
        event_type="run_queued",
        stage="queued",
        message="Agent 任务已入队，等待本机 worker 执行",
        detail={"job_id": job.id, "platforms": platforms, "from_action_stage": previous_stage},
    )
    db.refresh(run)
    return run


@router.get(
    "/workspaces/{workspace_id}/actions/{action_id}/agent-runs",
    response_model=list[AgentRunRead],
)
def list_action_agent_runs(
    workspace_id: int,
    action_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    scoped_or_404(db, GeoOptimizationAction, workspace_id, action_id)
    return list(
        db.scalars(
            select(GeoAgentRun)
            .where(GeoAgentRun.workspace_id == workspace_id, GeoAgentRun.action_id == action_id)
            .order_by(GeoAgentRun.id.desc())
        )
    )


def _agent_run_or_404(db: Session, workspace_id: int, run_id: int) -> GeoAgentRun:
    run = db.get(GeoAgentRun, run_id)
    if run is None or run.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return run


AGENT_PROGRESS_STAGES = (
    ("preparing_context", "整理真实证据", 10),
    ("researching_platform", "查阅平台规则", 20),
    ("researching_brand", "核对品牌与素材", 20),
    ("adapting_platforms", "生成母稿与平台稿", 35),
    ("awaiting_review", "核对事实并等待审核", 15),
)


def _utc_datetime(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _build_agent_run_progress(db: Session, run: GeoAgentRun) -> dict:
    events = list(
        db.scalars(
            select(GeoAgentEvent)
            .where(GeoAgentEvent.agent_run_id == run.id)
            .order_by(GeoAgentEvent.sequence)
        )
    )
    attempt_markers = [
        index
        for index, event in enumerate(events)
        if event.event_type in {"run_queued", "resume_queued", "revision_queued"}
    ]
    if attempt_markers:
        attempt_boundary = attempt_markers[-1]
        attempt_number = len(attempt_markers)
    else:
        # Older persisted runs may predate explicit queue events. Their latest
        # preparing_context event is the safest available attempt boundary.
        attempt_boundary = max(
            (
                index
                for index, event in enumerate(events)
                if event.event_type == "stage_started" and event.stage == "preparing_context"
            ),
            default=0,
        )
        attempt_number = 1
    attempt_events = events[attempt_boundary:]
    attempt_started_at = next(
        (
            event.created_at
            for event in attempt_events
            if event.event_type == "stage_started" and event.stage == "preparing_context"
        ),
        attempt_events[0].created_at if attempt_events else (run.started_at or run.created_at),
    )
    artifacts = list(
        db.scalars(
            select(GeoAgentArtifact)
            .where(GeoAgentArtifact.agent_run_id == run.id)
            .order_by(GeoAgentArtifact.id)
        )
    )
    attempt_artifacts = [
        artifact
        for artifact in artifacts
        if _utc_datetime(artifact.created_at) >= _utc_datetime(attempt_started_at)
    ]
    stage_index = {key: index for index, (key, _label, _weight) in enumerate(AGENT_PROGRESS_STAGES)}
    latest_by_stage = {
        key: next((event for event in reversed(attempt_events) if event.stage == key), None)
        for key in stage_index
    }
    observed_indices = [stage_index[event.stage] for event in attempt_events if event.stage in stage_index]
    current_index = stage_index.get(run.stage)
    if current_index is None and observed_indices:
        current_index = max(observed_indices)

    failure_status = run.status in {"cancelled", "failed", "blocked"}
    active_status = run.status in ACTIVE_AGENT_RUN_STATUSES
    stages = []
    progress_percent = 0
    for index, (key, label, weight) in enumerate(AGENT_PROGRESS_STAGES):
        event = latest_by_stage[key]
        state = "waiting"
        if run.status == "awaiting_review":
            state = "waiting_human" if key == "awaiting_review" else "done"
            progress_percent += weight
        elif failure_status and current_index is not None:
            if index < current_index:
                state = "done"
                progress_percent += weight
            elif index == current_index:
                state = "failed"
        elif active_status and current_index is not None:
            if index < current_index:
                state = "done"
                progress_percent += weight
            elif index == current_index:
                if event is not None and event.event_type == "stage_completed":
                    state = "done"
                    progress_percent += weight
                else:
                    state = "running"
        stages.append(
            {
                "key": key,
                "label": label,
                "state": state,
                "message": event.message if event is not None else None,
                "event_sequence": event.sequence if event is not None else None,
                "updated_at": event.created_at if event is not None else None,
            }
        )

    timeout_seconds = max(60, min(int(get_settings().agent_run_timeout_seconds), 3600))
    started_at = attempt_started_at
    finished_at = run.finished_at or datetime.now(timezone.utc)
    elapsed_seconds = max(0, int((_utc_datetime(finished_at) - _utc_datetime(started_at)).total_seconds()))
    timeout_remaining_seconds = None
    if active_status:
        timeout_remaining_seconds = max(0, timeout_seconds - elapsed_seconds)
    return {
        "run": run,
        "stages": stages,
        "attempt_number": attempt_number,
        "attempt_event_count": len(attempt_events),
        "attempt_started_at": attempt_started_at,
        "progress_percent": progress_percent,
        "elapsed_seconds": elapsed_seconds,
        "timeout_seconds": timeout_seconds,
        "timeout_remaining_seconds": timeout_remaining_seconds,
        "event_count": len(events),
        "events": events,
        "artifacts": [
            {
                "id": artifact.id,
                "artifact_kind": artifact.artifact_kind,
                "sha256": artifact.sha256,
                "size_bytes": artifact.size_bytes,
                "created_at": artifact.created_at,
            }
            for artifact in attempt_artifacts
        ],
    }


@router.get(
    "/workspaces/{workspace_id}/agent-runs/{run_id}",
    response_model=AgentRunRead,
)
def read_agent_run(
    workspace_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    return _agent_run_or_404(db, workspace_id, run_id)


@router.get(
    "/workspaces/{workspace_id}/agent-runs/{run_id}/progress",
    response_model=AgentRunProgressRead,
)
def read_agent_run_progress(
    workspace_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    run = _agent_run_or_404(db, workspace_id, run_id)
    return _build_agent_run_progress(db, run)


@router.post(
    "/workspaces/{workspace_id}/agent-runs/{run_id}/visual-captures",
    response_model=AgentRunProgressRead,
)
def capture_agent_run_visuals(
    workspace_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace = workspace_or_404(db, user, workspace_id)
    run = _agent_run_or_404(db, workspace_id, run_id)
    if run.status != "awaiting_review":
        raise HTTPException(
            status_code=409,
            detail="Agent 内容完成后才能补采官网素材",
        )
    asset_id = int((run.result_snapshot or {}).get("asset_id") or 0)
    asset = scoped_or_404(db, GeoContentAsset, workspace_id, asset_id)
    variants = list(
        db.scalars(
            select(GeoPlatformVariant)
            .where(GeoPlatformVariant.content_asset_id == asset.id)
            .order_by(GeoPlatformVariant.id)
        )
    )
    manifest_items = [item for variant in variants for item in (variant.image_manifest or [])]
    referenced_artifact_ids = {
        int(item.get("artifact_id") or 0)
        for item in manifest_items
        if int(item.get("artifact_id") or 0) > 0
    }
    referenced_artifacts = {
        artifact.id: artifact
        for artifact in db.scalars(
            select(GeoAgentArtifact).where(
                GeoAgentArtifact.agent_run_id == run.id,
                GeoAgentArtifact.id.in_(referenced_artifact_ids or {-1}),
            )
        )
    }
    manifest_is_verified = bool(manifest_items) and all(
        item.get("quality_gate") == "passed"
        and (artifact := referenced_artifacts.get(int(item.get("artifact_id") or 0))) is not None
        and artifact.artifact_kind == "official_page_screenshot"
        and (artifact.metadata_json or {}).get("quality_gate") == "passed"
        for item in manifest_items
    )
    if manifest_is_verified:
        run.stage = "awaiting_review"
        db.add(run)
        db.commit()
        return _build_agent_run_progress(db, run)
    if manifest_items:
        for artifact in referenced_artifacts.values():
            if artifact.artifact_kind == "official_page_screenshot":
                artifact.artifact_kind = "invalid_page_screenshot"
                artifact.metadata_json = {
                    **(artifact.metadata_json or {}),
                    "status": "invalid",
                    "invalid_reason": "capture_quality_unverified",
                }
                db.add(artifact)
        for variant in variants:
            variant.image_manifest = []
            db.add(variant)

    structured = db.scalar(
        select(GeoAgentArtifact)
        .where(
            GeoAgentArtifact.agent_run_id == run.id,
            GeoAgentArtifact.artifact_kind == "structured_result",
        )
        .order_by(GeoAgentArtifact.id.desc())
    )
    candidates: list[dict] = []
    if structured is not None:
        try:
            root = ARTIFACT_ROOT.resolve(strict=True)
            result_path = Path(structured.uri).resolve(strict=True)
            result_path.relative_to(root)
            payload = result_path.read_bytes()
            if sha256(payload).hexdigest() == structured.sha256:
                result = json.loads(payload).get("result") or {}
                candidates = list(result.get("visual_assets") or [])
        except (OSError, ValueError, json.JSONDecodeError, AttributeError):
            candidates = []
    if not candidates and workspace.website_url:
        candidates = [
            {
                "source_url": workspace.website_url,
                "alt_text": f"{workspace.brand_name}官网页面",
                "purpose": "官网当前品牌呈现，供内容审核和配图选择",
                "recommended_platforms": run.selected_platforms,
            }
        ]
    capture_outcome, manifest = capture_agent_visuals(
        db,
        run,
        official_website=workspace.website_url,
        candidates=candidates,
        output_directory=ARTIFACT_ROOT / str(workspace_id) / str(run.id) / "visuals",
    )
    snapshot = dict(run.result_snapshot or {})
    snapshot["visual_asset_count"] = len(manifest)
    snapshot["visual_capture_status"] = capture_outcome.status
    run.result_snapshot = snapshot
    run.stage = "awaiting_review"
    if manifest:
        for variant in variants:
            variant.image_manifest = [
                item
                for item in manifest
                if not item.get("recommended_platforms")
                or variant.platform_key in item.get("recommended_platforms", [])
            ]
            db.add(variant)
        db.add(run)
        db.commit()
        return _build_agent_run_progress(db, run)
    db.add(run)
    db.commit()
    detail_by_reason = {
        "browser_bridge_not_connected": "未检测到已连接的本机浏览器桥接，请开启 OpenCLI 扩展后重试",
        "no_official_domain_candidate": "Agent 没有提供可验证的官方同域素材页",
        "official_page_open_failed": "官方页面无法在本机浏览器中打开",
        "official_page_identity_missing": "官方页面已打开，但未获得可验证的浏览器页签",
        "official_page_render_timeout": "官方页面渲染超时，未将空白画面归档",
        "official_page_visual_empty": "官方页面没有可见正文或图像，未将空白画面归档",
        "official_page_screenshot_command_failed": "官方页面已渲染，但浏览器截图命令失败",
        "official_page_screenshot_file_missing": "浏览器已执行截图，但私密工件目录没有收到图片",
        "official_page_screenshot_empty": "浏览器截图文件为空，未将它计为真实素材",
    }
    raise HTTPException(
        status_code=409,
        detail=detail_by_reason.get(
            capture_outcome.reason or "",
            "本次官网素材未采集，正文与审核状态未受影响",
        ),
    )


@router.get(
    "/workspaces/{workspace_id}/agent-runs/{run_id}/events",
    response_model=list[AgentEventRead],
)
def list_agent_events(
    workspace_id: int,
    run_id: int,
    after: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    _agent_run_or_404(db, workspace_id, run_id)
    return list(
        db.scalars(
            select(GeoAgentEvent)
            .where(GeoAgentEvent.agent_run_id == run_id, GeoAgentEvent.sequence > after)
            .order_by(GeoAgentEvent.sequence)
        )
    )


@router.get(
    "/workspaces/{workspace_id}/agent-runs/{run_id}/events/stream",
)
def stream_agent_events(
    workspace_id: int,
    run_id: int,
    after: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    _agent_run_or_404(db, workspace_id, run_id)

    async def event_stream():
        cursor = after
        idle_terminal_polls = 0
        while True:
            with SessionLocal() as stream_db:
                run = stream_db.get(GeoAgentRun, run_id)
                events = list(
                    stream_db.scalars(
                        select(GeoAgentEvent)
                        .where(
                            GeoAgentEvent.agent_run_id == run_id,
                            GeoAgentEvent.sequence > cursor,
                        )
                        .order_by(GeoAgentEvent.sequence)
                    )
                )
                for event in events:
                    cursor = event.sequence
                    payload = AgentEventRead.model_validate(event).model_dump(mode="json")
                    yield f"id: {cursor}\nevent: agent_event\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                terminal = run is None or run.status in {"awaiting_review", "cancelled", "failed", "blocked"}
            if terminal and not events:
                idle_terminal_polls += 1
                if idle_terminal_polls >= 2:
                    yield "event: end\ndata: {}\n\n"
                    break
            else:
                idle_terminal_polls = 0
            if not events:
                yield ": keepalive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/workspaces/{workspace_id}/agent-runs/{run_id}/artifacts",
    response_model=list[AgentArtifactRead],
)
def list_agent_artifacts(
    workspace_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    _agent_run_or_404(db, workspace_id, run_id)
    return list(
        db.scalars(
            select(GeoAgentArtifact)
            .where(GeoAgentArtifact.agent_run_id == run_id)
            .order_by(GeoAgentArtifact.id)
        )
    )


@router.get(
    "/workspaces/{workspace_id}/agent-artifacts/{artifact_id}/content",
    response_class=FileResponse,
)
def read_agent_artifact_content(
    workspace_id: int,
    artifact_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    artifact = scoped_or_404(db, GeoAgentArtifact, workspace_id, artifact_id)
    if artifact.artifact_kind != "official_page_screenshot":
        raise HTTPException(status_code=404, detail="Visual artifact not found")
    try:
        root = AGENT_ARTIFACT_ROOT.resolve(strict=True)
        artifact_path = Path(artifact.uri).resolve(strict=True)
        artifact_path.relative_to(root)
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="Visual artifact file not found") from None
    if not artifact_path.is_file():
        raise HTTPException(status_code=404, detail="Visual artifact file not found")
    payload = artifact_path.read_bytes()
    if sha256(payload).hexdigest() != artifact.sha256:
        raise HTTPException(status_code=409, detail="Visual artifact integrity check failed")
    return FileResponse(
        artifact_path,
        media_type="image/png",
        headers={
            "Cache-Control": "private, max-age=3600",
            "ETag": f'"{artifact.sha256}"',
        },
    )


@router.post(
    "/workspaces/{workspace_id}/agent-runs/{run_id}/interrupt",
    response_model=AgentRunRead,
)
def interrupt_agent_run(
    workspace_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    run = _agent_run_or_404(db, workspace_id, run_id)
    if run.status not in {"queued", "resuming", "running", "cancelling"}:
        raise HTTPException(status_code=409, detail=f"Cannot interrupt Agent run in {run.status}")
    now = datetime.now(timezone.utc)
    job = db.get(QueueJob, run.job_id) if run.job_id else None
    if run.status in {"queued", "resuming"} and job is not None and job.status == "pending":
        run.status = "cancelled"
        run.stage = "cancelled"
        run.cancel_requested_at = now
        run.error_code = "user_interrupted"
        run.error_message = "Agent run was cancelled before the worker started"
        run.finished_at = now
        job.status = "success"
        job.finished_at = now
        job.error_message = None
        job.payload_json = {
            **dict(job.payload_json or {}),
            "stage": "cancelled",
            "agent_status": "cancelled",
            "cancelled_before_start": True,
        }
        action = db.get(GeoOptimizationAction, run.action_id)
        if action is not None:
            action.stage = "reviewing" if (run.result_snapshot or {}).get("asset_id") else "selected"
            action.blocked_reason = None
        db.commit()
        append_agent_event(
            db,
            run,
            event_type="run_cancelled",
            stage="cancelled",
            message="Agent 尚未开始执行，排队任务已立即取消",
            detail={"requested_by_user_id": user.id, "job_id": job.id},
        )
        return run
    if run.cancel_requested_at is None:
        run.cancel_requested_at = now
    run.status = "cancelling"
    db.commit()
    append_agent_event(
        db,
        run,
        event_type="interrupt_requested",
        stage=run.stage,
        message="已请求中止；worker 将在下一个 SDK 事件点发送真实 interrupt",
        detail={"requested_by_user_id": user.id},
    )
    return run


@router.post(
    "/workspaces/{workspace_id}/agent-runs/{run_id}/resume",
    response_model=AgentRunRead,
    status_code=202,
)
def resume_agent_run(
    workspace_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    run = _agent_run_or_404(db, workspace_id, run_id)
    if run.status not in {"cancelled", "failed"} or not run.codex_thread_id:
        raise HTTPException(status_code=409, detail="Only an interrupted/failed run with a Codex thread can resume")
    _assert_agent_capacity(db, workspace_id, exclude_run_id=run.id)
    job = QueueJob(
        job_type="geo_agent.run",
        status="pending",
        priority=20,
        scheduled_at=datetime.now(timezone.utc),
        max_attempts=1,
        payload_json={
            "project_id": 0,
            "workspace_id": workspace_id,
            "action_id": run.action_id,
            "agent_run_id": run.id,
            "actor_user_id": user.id,
            "resume": True,
        },
    )
    db.add(job)
    db.flush()
    run.job_id = job.id
    run.status = "resuming"
    run.cancel_requested_at = None
    run.error_code = None
    run.error_message = None
    run.finished_at = None
    db.commit()
    append_agent_event(
        db,
        run,
        event_type="resume_queued",
        stage="queued",
        message="已使用原 Codex thread 恢复任务",
        detail={"job_id": job.id},
    )
    return run


@router.post(
    "/workspaces/{workspace_id}/agent-runs/{run_id}/revise",
    response_model=AgentRunRead,
    status_code=202,
)
def revise_agent_run(
    workspace_id: int,
    run_id: int,
    payload: AgentRevisionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    run = _agent_run_or_404(db, workspace_id, run_id)
    asset = scoped_or_404(db, GeoContentAsset, workspace_id, payload.content_asset_id)
    brief = scoped_or_404(db, GeoContentBrief, workspace_id, asset.brief_id)
    if brief.action_id != run.action_id or int((run.result_snapshot or {}).get("asset_id") or 0) != asset.id:
        raise HTTPException(status_code=409, detail="The rejected asset is not the current result of this Agent run")
    if run.status != "awaiting_review" or asset.status != "changes_requested" or not run.codex_thread_id:
        raise HTTPException(
            status_code=409,
            detail="Only the current rejected draft with an existing Codex thread can be revised",
        )
    _assert_agent_capacity(db, workspace_id, exclude_run_id=run.id)
    review = db.scalar(
        select(GeoContentReview)
        .where(
            GeoContentReview.workspace_id == workspace_id,
            GeoContentReview.subject_type == "content_asset",
            GeoContentReview.subject_id == asset.id,
            GeoContentReview.verdict == "changes_requested",
        )
        .order_by(GeoContentReview.id.desc())
    )
    feedback = [
        str(issue.get("message") or "").strip()
        for issue in (review.issues or [])
        if str(issue.get("message") or "").strip()
    ] if review else []
    if not feedback:
        raise HTTPException(status_code=409, detail="The rejected draft has no stored human feedback")
    job = QueueJob(
        job_type="geo_agent.run",
        status="pending",
        priority=20,
        scheduled_at=datetime.now(timezone.utc),
        max_attempts=1,
        payload_json={
            "project_id": 0,
            "workspace_id": workspace_id,
            "action_id": run.action_id,
            "agent_run_id": run.id,
            "actor_user_id": user.id,
            "resume": True,
            "revision_of_asset_id": asset.id,
        },
    )
    db.add(job)
    db.flush()
    run.job_id = job.id
    run.status = "resuming"
    run.stage = "queued"
    run.cancel_requested_at = None
    run.error_code = None
    run.error_message = None
    run.finished_at = None
    action = scoped_or_404(db, GeoOptimizationAction, workspace_id, run.action_id)
    action.stage = "generating"
    action.blocked_reason = None
    db.commit()
    append_agent_event(
        db,
        run,
        event_type="revision_queued",
        stage="queued",
        message="已根据人工意见排队修订；旧版本保留可追溯",
        detail={"job_id": job.id, "source_asset_id": asset.id, "feedback": feedback},
    )
    return run


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
    completed_retest = db.scalar(
        select(GeoReobservation).where(
            GeoReobservation.action_id == action.id,
            GeoReobservation.status == "completed",
            GeoReobservation.conclusion.in_(("improved", "unchanged", "regressed")),
        )
    )
    if payload.status == "closed" and not completed_retest:
        raise HTTPException(
            status_code=422,
            detail="完成同口径复测并获得可比较结论后才能关闭行动",
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
        status="legacy_recorded",
        conclusion="insufficient_evidence",
        measured_delta={
            "comparable": False,
            "reason": "legacy_single_evidence_has_no_comparable_batch_scope",
            "submitted_conclusion": payload.conclusion,
            "submitted_delta": payload.measured_delta,
        },
        completed_at=datetime.now(timezone.utc),
    )
    action.status = "in_progress"
    action.stage = "retest_inconclusive"
    action.blocked_reason = "单条证据无法形成同口径复测结论，请使用行动复测入口。"
    db.add(row)
    db.commit()
    return {"id": row.id, "action_id": action.id, "status": action.status}


def _action_retest_read(db: Session, row: GeoReobservation) -> dict:
    batch_summary = None
    retest_ledger_batch = (
        db.get(GeoObservationBatch, row.retest_batch_id) if row.retest_batch_id else None
    )
    if retest_ledger_batch is None and row.retest_queue_job_id:
        retest_ledger_batch = db.scalar(
            select(GeoObservationBatch).where(
                GeoObservationBatch.queue_job_id == row.retest_queue_job_id
            )
        )
    if retest_ledger_batch is not None:
        batch_summary = _official_api_batch_summary(db, retest_ledger_batch)
        if row.status not in {"completed", "failed"}:
            if batch_summary["status"] in {"pending", "running"}:
                row.status = "queued" if batch_summary["status"] == "pending" else "running"
            else:
                baseline_batch = db.get(GeoObservationBatch, row.baseline_batch_id)
                retest_batch = retest_ledger_batch
                scope = row.scope_snapshot or {}
                question_plan_id = int(scope.get("question_plan_id") or 0)
                provider_ids = [int(value) for value in scope.get("provider_ids") or []]
                if baseline_batch is None or retest_batch is None or not question_plan_id or not provider_ids:
                    row.status = "failed"
                    row.conclusion = "insufficient_evidence"
                    row.measured_delta = {
                        "comparable": False,
                        "reason": "retest_scope_or_batch_missing",
                    }
                else:
                    baseline_metrics = build_batch_metrics(
                        db,
                        baseline_batch,
                        question_plan_id=question_plan_id,
                        provider_ids=provider_ids,
                    )
                    retest_metrics = build_batch_metrics(
                        db,
                        retest_batch,
                        question_plan_id=question_plan_id,
                        provider_ids=provider_ids,
                    )
                    conclusion, measured_delta = compare_batches(
                        baseline_batch,
                        retest_batch,
                        baseline_metrics,
                        retest_metrics,
                    )
                    row.baseline_metrics = baseline_metrics
                    row.retest_metrics = retest_metrics
                    row.conclusion = conclusion
                    row.measured_delta = measured_delta
                    row.status = "completed"
                    row.completed_at = datetime.now(timezone.utc)
                    action = db.get(GeoOptimizationAction, row.action_id)
                    if action:
                        if conclusion in {"improved", "unchanged", "regressed"}:
                            action.status = "verified"
                            action.stage = "verified"
                            action.completed_at = row.completed_at
                            action.blocked_reason = None
                            if action.opportunity_id:
                                opportunity = db.get(
                                    GeoActionOpportunity, action.opportunity_id
                                )
                                if opportunity and opportunity.workspace_id == row.workspace_id:
                                    opportunity.status = "completed"
                        else:
                            action.status = "in_progress"
                            action.stage = "retest_inconclusive"
                            action.blocked_reason = "复测已结束，但样本或模型版本不满足同口径比较要求。"
                    db.add(
                        GeoActionEvent(
                            workspace_id=row.workspace_id,
                            action_id=row.action_id,
                            event_type="comparable_retest_completed",
                            from_stage="retesting",
                            to_stage=action.stage if action else "retest_completed",
                            actor_type="system",
                            job_id=row.retest_queue_job_id,
                            detail={
                                "reobservation_id": row.id,
                                "conclusion": conclusion,
                                "comparable": bool(measured_delta.get("comparable")),
                                "baseline_batch_id": row.baseline_batch_id,
                                "retest_batch_id": row.retest_batch_id,
                            },
                        )
                    )
            db.commit()
            db.refresh(row)
    elif row.status not in {"completed", "failed"}:
        row.status = "failed"
        row.conclusion = "insufficient_evidence"
        row.measured_delta = {"comparable": False, "reason": "queue_job_missing"}
        action = db.get(GeoOptimizationAction, row.action_id)
        if action:
            action.status = "in_progress"
            action.stage = "retest_failed"
            action.blocked_reason = "复测队列记录不存在，请重新创建复测。"
        db.commit()
        db.refresh(row)
    return {
        "id": row.id,
        "action_id": row.action_id,
        "workspace_id": row.workspace_id,
        "status": row.status,
        "baseline_batch_id": row.baseline_batch_id,
        "retest_batch_id": row.retest_batch_id,
        "retest_queue_job_id": row.retest_queue_job_id,
        "scope_snapshot": row.scope_snapshot or {},
        "baseline_metrics": row.baseline_metrics or {},
        "retest_metrics": row.retest_metrics or {},
        "conclusion": row.conclusion,
        "measured_delta": row.measured_delta or {},
        "batch": batch_summary,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
    }


@router.get(
    "/workspaces/{workspace_id}/actions/{action_id}/retest",
    response_model=ActionRetestRead,
)
def read_action_retest(
    workspace_id: int,
    action_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    action = scoped_or_404(db, GeoOptimizationAction, workspace_id, action_id)
    row = db.scalar(select(GeoReobservation).where(GeoReobservation.action_id == action.id))
    if row is None:
        raise HTTPException(status_code=404, detail="该行动还没有复测任务")
    return _action_retest_read(db, row)


@router.get(
    "/workspaces/{workspace_id}/action-workbench-state",
    response_model=ActionWorkbenchStateRead,
)
def read_action_workbench_state(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return the persisted action workflow ledger without per-action HTTP fan-out."""
    workspace_or_404(db, user, workspace_id)
    agent_runs = list(
        db.scalars(
            select(GeoAgentRun)
            .where(GeoAgentRun.workspace_id == workspace_id)
            .order_by(GeoAgentRun.id.desc())
        )
    )
    asset_ids = list(
        dict.fromkeys(
            asset_id
            for run in agent_runs
            if isinstance(run.result_snapshot, dict)
            and isinstance(asset_id := run.result_snapshot.get("asset_id"), int)
            and asset_id > 0
        )
    )
    assets_by_id = (
        {
            asset.id: asset
            for asset in db.scalars(
                select(GeoContentAsset).where(
                    GeoContentAsset.workspace_id == workspace_id,
                    GeoContentAsset.id.in_(asset_ids),
                )
            )
        }
        if asset_ids
        else {}
    )
    distribution_runs = list(
        db.scalars(
            select(GeoDistributionRun)
            .where(GeoDistributionRun.workspace_id == workspace_id)
            .order_by(GeoDistributionRun.id.desc())
        )
    )
    retest_rows = list(
        db.scalars(
            select(GeoReobservation)
            .where(GeoReobservation.workspace_id == workspace_id)
            .order_by(GeoReobservation.id.desc())
        )
    )
    return {
        "agent_runs": agent_runs,
        "review_packages": [
            _content_review_package(db, assets_by_id[asset_id])
            for asset_id in asset_ids
            if asset_id in assets_by_id
        ],
        "distribution_runs": [_distribution_read(db, run) for run in distribution_runs],
        "retests": [_action_retest_read(db, row) for row in retest_rows],
    }


@router.post(
    "/workspaces/{workspace_id}/actions/{action_id}/retest",
    response_model=ActionRetestRead,
    status_code=202,
)
def create_action_retest(
    workspace_id: int,
    action_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    action = scoped_or_404(db, GeoOptimizationAction, workspace_id, action_id)
    existing = db.scalar(select(GeoReobservation).where(GeoReobservation.action_id == action.id))
    if existing and existing.status in {"preparing", "queued", "running"}:
        return _action_retest_read(db, existing)
    if existing and existing.status == "completed" and existing.conclusion != "insufficient_evidence":
        return _action_retest_read(db, existing)

    published_run = None
    for distribution in db.scalars(
        select(GeoDistributionRun)
        .where(
            GeoDistributionRun.workspace_id == workspace_id,
            GeoDistributionRun.action_id == action.id,
        )
        .order_by(GeoDistributionRun.id.desc())
    ):
        targets = list(
            db.scalars(
                select(GeoDistributionTarget).where(
                    GeoDistributionTarget.distribution_run_id == distribution.id
                )
            )
        )
        if targets and all(
            target.human_publish_status == "published"
            and target.public_url
            and target.publication_verification_status == "publicly_verified"
            for target in targets
        ):
            published_run = (distribution, targets)
            break
    if published_run is None:
        raise HTTPException(
            status_code=409,
            detail="请先为全部平台记录并通过公网校验的真实公开文章 URL",
        )

    baseline_batch_id = int((action.baseline_snapshot or {}).get("batch_id") or 0)
    baseline_batch = db.get(GeoObservationBatch, baseline_batch_id)
    if baseline_batch is None or baseline_batch.workspace_id != workspace_id:
        raise HTTPException(status_code=409, detail="行动缺少可追溯的基线观测批次")
    if baseline_batch.status != "completed":
        raise HTTPException(status_code=409, detail="基线观测批次尚未完整结束")
    if not action.question_plan_id:
        raise HTTPException(status_code=409, detail="行动未关联原始问题，不能创建同口径复测")
    configuration = baseline_batch.configuration or {}
    provider_ids = [
        int(item.get("id") or 0)
        for item in configuration.get("providers") or []
        if isinstance(item, dict) and int(item.get("id") or 0) > 0
    ]
    provider_ids = list(dict.fromkeys(provider_ids))
    if not provider_ids:
        raise HTTPException(status_code=409, detail="基线批次没有可复用的模型渠道")
    baseline_metrics = build_batch_metrics(
        db,
        baseline_batch,
        question_plan_id=action.question_plan_id,
        provider_ids=provider_ids,
    )
    if (
        int(baseline_metrics.get("eligible_samples") or 0) < 1
        or baseline_metrics.get("eligible_samples") != baseline_metrics.get("expected_samples")
    ):
        raise HTTPException(status_code=409, detail="基线样本不满足真实联网证据门槛，不能做可比复测")

    now = datetime.now(timezone.utc)
    distribution, publication_targets = published_run
    previous_attempts = []
    if existing:
        previous_attempts = list((existing.scope_snapshot or {}).get("previous_attempts") or [])
        previous_attempts.append(
            {
                "retest_batch_id": existing.retest_batch_id,
                "retest_queue_job_id": existing.retest_queue_job_id,
                "status": existing.status,
                "conclusion": existing.conclusion,
                "completed_at": existing.completed_at.isoformat() if existing.completed_at else None,
            }
        )
        row = existing
    else:
        row = GeoReobservation(action_id=action.id, workspace_id=workspace_id)
        db.add(row)
    row.status = "preparing"
    row.baseline_batch_id = baseline_batch.id
    row.retest_batch_id = None
    row.retest_queue_job_id = None
    row.scope_snapshot = {
        "schema": "comparable-action-retest/v1",
        "question_plan_id": action.question_plan_id,
        "provider_ids": provider_ids,
        "repeat_count": baseline_batch.repeat_count,
        "baseline_batch_id": baseline_batch.id,
        "distribution_run_id": distribution.id,
        "published_targets": [
            {
                "platform_key": target.platform_key,
                "public_url": target.public_url,
                "published_at": target.published_at.isoformat() if target.published_at else None,
            }
            for target in publication_targets
        ],
        "previous_attempts": previous_attempts,
    }
    row.baseline_metrics = baseline_metrics
    row.retest_metrics = {}
    row.conclusion = "pending"
    row.measured_delta = {}
    row.started_at = now
    row.completed_at = None
    db.flush()
    try:
        batch_receipt = create_provider_web_search_batch(
            workspace_id,
            OfficialApiObservationBatchCreate(
                provider_ids=provider_ids,
                question_plan_ids=[action.question_plan_id],
                repeat_count=baseline_batch.repeat_count,
            ),
            db,
            user,
        )
    except Exception:
        db.rollback()
        raise
    retest_batch_id = int(batch_receipt["batch_id"])
    retest_batch = db.get(GeoObservationBatch, retest_batch_id)
    if retest_batch is None or retest_batch.workspace_id != workspace_id:
        row.status = "failed"
        row.conclusion = "insufficient_evidence"
        row.measured_delta = {"comparable": False, "reason": "ledger_batch_missing"}
        db.commit()
        raise HTTPException(status_code=500, detail="复测队列已创建，但统一观测账本缺失")
    queue_job_id = int(retest_batch.queue_job_id or 0)
    queue_job = db.get(QueueJob, queue_job_id) if queue_job_id else None
    if queue_job is None or queue_job.job_type != "geo_observation.batch":
        row.status = "failed"
        row.conclusion = "insufficient_evidence"
        row.measured_delta = {"comparable": False, "reason": "queue_job_missing"}
        db.commit()
        raise HTTPException(status_code=500, detail="复测账本已创建，但队列任务缺失")
    retest_batch.source_type = "action_retest"
    retest_batch.configuration = {
        **(retest_batch.configuration or {}),
        "action_retest": {
            "action_id": action.id,
            "reobservation_id": row.id,
            "baseline_batch_id": baseline_batch.id,
        },
    }
    row.retest_batch_id = retest_batch.id
    row.retest_queue_job_id = queue_job_id
    row.status = "queued"
    action.status = "in_progress"
    previous_stage = action.stage
    action.stage = "retesting"
    action.blocked_reason = None
    db.add(
        GeoActionEvent(
            workspace_id=workspace_id,
            action_id=action.id,
            event_type="comparable_retest_queued",
            from_stage=previous_stage,
            to_stage="retesting",
            actor_type="user",
            actor_user_id=user.id,
            job_id=queue_job_id,
            detail={
                "reobservation_id": row.id,
                "baseline_batch_id": baseline_batch.id,
                "retest_batch_id": retest_batch.id,
                "question_plan_id": action.question_plan_id,
                "provider_ids": provider_ids,
                "repeat_count": baseline_batch.repeat_count,
            },
        )
    )
    db.commit()
    db.refresh(row)
    return _action_retest_read(db, row)


def _verify_brand_fact_source_or_http_error(source_url: str, statement: str) -> dict:
    try:
        return verify_brand_fact_source(source_url, statement)
    except WebsiteAuditTargetError as exc:
        raise HTTPException(
            status_code=422,
            detail="公开来源必须是可从公网访问的 HTTP(S) 地址，不能指向本机或内网。",
        ) from exc
    except BrandFactSourceVerificationError as exc:
        reason = str(exc)
        if reason == "brand_fact_statement_not_found":
            detail = "来源页公开正文及其同域前端资源中都没有找到这段完整陈述；请粘贴页面实际展示的原文。"
            status_code = 422
        elif reason == "brand_fact_source_not_html":
            detail = "当前只支持可公开读取的 HTML 来源页。"
            status_code = 422
        else:
            detail = "暂时无法从公网读取该来源；本次不会把它保存为可用品牌事实。"
            status_code = 409
        raise HTTPException(status_code=status_code, detail=detail) from exc


def _record_brand_fact_verification(
    db: Session,
    *,
    workspace: GeoWorkspace,
    fact: GeoBrandFact,
    verification: dict,
    user: User,
) -> None:
    record_audit_log(
        db,
        user=user,
        action=BRAND_FACT_VERIFICATION_ACTION,
        resource_type="geo_brand_fact",
        resource_id=fact.id,
        company_id=workspace.company_id,
        detail={
            "workspace_id": workspace.id,
            "source_url": fact.source_url,
            "statement_sha256": statement_fingerprint(fact.statement),
            "verification": verification,
        },
    )


def _record_brand_fact_verification_failure(
    db: Session,
    *,
    workspace: GeoWorkspace,
    source_url: str,
    statement: str,
    error: HTTPException,
    user: User,
    fact: GeoBrandFact | None = None,
) -> None:
    record_audit_log(
        db,
        user=user,
        action=BRAND_FACT_VERIFICATION_FAILED_ACTION,
        resource_type="geo_brand_fact" if fact is not None else "geo_brand_fact_candidate",
        resource_id=fact.id if fact is not None else None,
        company_id=workspace.company_id,
        detail={
            "workspace_id": workspace.id,
            "source_url": source_url,
            "statement_sha256": statement_fingerprint(statement),
            "verification": {
                "status": "failed",
                "http_status": error.status_code,
                "detail": str(error.detail),
            },
        },
    )


@router.get("/workspaces/{workspace_id}/brand-facts", response_model=list[BrandFactRead])
def list_brand_facts(
    workspace_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    workspace_or_404(db, user, workspace_id)
    facts = list(
        db.scalars(
            select(GeoBrandFact)
            .where(GeoBrandFact.workspace_id == workspace_id)
            .order_by(GeoBrandFact.id.desc())
        )
    )
    return [brand_fact_read(db, fact) for fact in facts]


@router.post(
    "/workspaces/{workspace_id}/brand-facts/{fact_id}/source-candidates",
    response_model=BrandFactSourceCandidatesRead,
)
def discover_brand_fact_candidates(
    workspace_id: int,
    fact_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace = workspace_or_404(db, user, workspace_id)
    fact = scoped_or_404(db, GeoBrandFact, workspace_id, fact_id)
    if not fact.source_url:
        raise HTTPException(status_code=409, detail="请先为这条事实配置公开来源 URL。")
    try:
        result = discover_brand_fact_source_candidates(
            fact.source_url,
            brand_name=workspace.brand_name,
            query_text=f"{fact.title} {fact.statement}",
        )
    except WebsiteAuditTargetError as exc:
        raise HTTPException(
            status_code=422,
            detail="公开来源必须是可从公网访问的 HTTP(S) 地址，不能指向本机或内网。",
        ) from exc
    except BrandFactSourceVerificationError as exc:
        reason = str(exc)
        if reason == "brand_fact_source_not_html":
            detail = "当前只支持从可公开读取的 HTML 来源页查找原文。"
            status_code = 422
        else:
            detail = "暂时无法读取该公开来源；本次没有生成或保存候选原文。"
            status_code = 409
        raise HTTPException(status_code=status_code, detail=detail) from exc

    candidates = list(result.get("candidates") or [])
    record_audit_log(
        db,
        user=user,
        action=BRAND_FACT_CANDIDATES_DISCOVERED_ACTION,
        resource_type="geo_brand_fact",
        resource_id=fact.id,
        company_id=workspace.company_id,
        detail={
            "workspace_id": workspace.id,
            "source_url": result["source_url"],
            "statement_sha256": statement_fingerprint(fact.statement),
            "checked_at": result["checked_at"],
            "candidate_count": len(candidates),
            "candidates": candidates,
        },
    )
    db.commit()
    return {"fact_id": fact.id, **result}


@router.post(
    "/workspaces/{workspace_id}/brand-facts", response_model=BrandFactRead, status_code=201
)
def create_brand_fact(
    workspace_id: int,
    payload: BrandFactCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace = workspace_or_404(db, user, workspace_id)
    try:
        verification = _verify_brand_fact_source_or_http_error(
            payload.source_url,
            payload.statement,
        )
    except HTTPException as exc:
        _record_brand_fact_verification_failure(
            db,
            workspace=workspace,
            source_url=payload.source_url,
            statement=payload.statement,
            error=exc,
            user=user,
        )
        db.commit()
        raise
    fact = GeoBrandFact(
        workspace_id=workspace_id,
        **{
            **payload.model_dump(),
            "source_url": str(verification["verified_url"]),
        },
    )
    db.add(fact)
    db.flush()
    _record_brand_fact_verification(
        db,
        workspace=workspace,
        fact=fact,
        verification=verification,
        user=user,
    )
    db.commit()
    db.refresh(fact)
    return brand_fact_read(db, fact)


@router.patch(
    "/workspaces/{workspace_id}/brand-facts/{fact_id}", response_model=BrandFactRead
)
def update_brand_fact(
    workspace_id: int,
    fact_id: int,
    payload: BrandFactUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace = workspace_or_404(db, user, workspace_id)
    fact = scoped_or_404(db, GeoBrandFact, workspace_id, fact_id)
    changes = payload.model_dump(exclude_unset=True)
    next_statement = str(changes.get("statement", fact.statement))
    next_source_url = changes.get("source_url", fact.source_url)
    next_status = str(changes.get("status", fact.status))
    if next_status == "active" and not next_source_url:
        raise HTTPException(
            status_code=409,
            detail="恢复使用前必须先配置可核验的公开来源。",
        )
    verification = None
    if next_status == "active" and (
        "source_url" in changes or "statement" in changes or changes.get("status") == "active"
    ):
        try:
            verification = _verify_brand_fact_source_or_http_error(
                str(next_source_url),
                next_statement,
            )
        except HTTPException as exc:
            _record_brand_fact_verification_failure(
                db,
                workspace=workspace,
                fact=fact,
                source_url=str(next_source_url),
                statement=next_statement,
                error=exc,
                user=user,
            )
            db.commit()
            raise
        changes["source_url"] = str(verification["verified_url"])
    for key, value in changes.items():
        setattr(fact, key, value)
    db.flush()
    if verification is not None:
        _record_brand_fact_verification(
            db,
            workspace=workspace,
            fact=fact,
            verification=verification,
            user=user,
        )
    db.commit()
    db.refresh(fact)
    return brand_fact_read(db, fact)


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


@router.get(
    "/workspaces/{workspace_id}/website-audits/latest",
    response_model=WebsiteAuditOverviewRead,
)
def get_latest_website_audit(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    workspace = workspace_or_404(db, user, workspace_id)
    latest = db.scalar(
        select(GeoWebsiteAudit)
        .where(GeoWebsiteAudit.workspace_id == workspace_id)
        .order_by(GeoWebsiteAudit.checked_at.desc(), GeoWebsiteAudit.id.desc())
    )
    return {"website_url": workspace.website_url, "latest": latest}


@router.post(
    "/workspaces/{workspace_id}/website-audits",
    response_model=WebsiteAuditRead,
    status_code=201,
)
def create_website_audit(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace = workspace_or_404(db, user, workspace_id)
    if not workspace.website_url:
        raise HTTPException(status_code=409, detail="Workspace website URL is not configured")
    try:
        result = audit_website(workspace.website_url, brand_name=workspace.brand_name)
    except WebsiteAuditTargetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    audit = GeoWebsiteAudit(
        workspace_id=workspace_id,
        requested_by_user_id=user.id,
        **result,
    )
    db.add(audit)
    db.flush()
    opportunity = materialize_website_opportunity(db, workspace, audit)
    db.add(
        GeoActionEvent(
            workspace_id=workspace_id,
            action_id=None,
            event_type="website_citation_audit_completed",
            actor_type="user",
            actor_user_id=user.id,
            detail={
                "website_audit_id": audit.id,
                "status": audit.status,
                "score": audit.score,
                "requested_url": audit.requested_url,
                "raw_html_sha256": audit.raw_html_sha256,
                "finding_codes": [item.get("code") for item in audit.findings],
                "opportunity_id": opportunity.id if opportunity else None,
            },
        )
    )
    record_audit_log(
        db,
        user=user,
        action="workspace.website_citation_audit.create",
        resource_type="geo_website_audit",
        resource_id=audit.id,
        detail={
            "workspace_id": workspace_id,
            "status": audit.status,
            "score": audit.score,
            "raw_html_sha256": audit.raw_html_sha256,
        },
    )
    db.commit()
    db.refresh(audit)
    return audit
