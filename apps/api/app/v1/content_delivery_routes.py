import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import WRITE_ROLES, get_current_user, require_roles
from app.services.job_queue import geo_job_payload
from app.db.session import get_db
from app.models import LLMProvider, QueueJob
from app.models.cleanroom_v1 import (
    GeoActionCompletionEvidence,
    GeoActionEvent,
    GeoActionOpportunity,
    GeoActionOpportunityEvidence,
    GeoActionTarget,
    GeoAgentArtifact,
    GeoAgentRun,
    GeoBrandFact,
    GeoContentAsset,
    GeoContentBrief,
    GeoContentClaim,
    GeoContentReview,
    GeoDistributionRun,
    GeoDistributionTarget,
    GeoEvidence,
    GeoOptimizationAction,
    GeoPlatformVariant,
    GeoQuestionPlan,
    GeoReobservation,
    GeoWebsiteAudit,
    GeoWorkspace,
)
from app.models.user import User
from app.schemas.search import QueueJobRead
from app.services.article_sync_adapter import get_article_sync_adapter
from app.services.llm_provider import diagnose_provider
from app.services.workspace_secrets import (
    DEEPSEEK_API_KEY,
    get_workspace_secret,
    resolve_article_sync_credentials,
)
from app.v1.action_workflow import synchronize_article_action_targets as v2_synchronize_article_action_targets
from app.v1.brand_facts import verified_active_brand_facts
from app.v1.platform_adaptation import adapt_asset
from app.v1.route_support import scoped_or_404, workspace_or_404
from app.v1.schemas import (
    ArticleAssistantClientResults,
    ArticleAssistantTaskRead,
    ContentAssetRead,
    ContentBriefCreate,
    ContentBriefRead,
    ContentGenerateRequest,
    ContentLibraryItemRead,
    ContentReviewDecision,
    ContentReviewPackageRead,
    DistributionClientResults,
    DistributionRunCreate,
    DistributionRunRead,
    HumanDraftReadbackRecord,
    HumanPublicationRecord,
    PlatformVariantCreate,
    PlatformVariantRead,
    PlatformVariantUpdate,
)
from app.v1.website_audit import (
    PublicationVerificationError,
    WebsiteAuditTargetError,
    verify_publication_page,
)
from app.v1.workspace_routes import _as_utc


router = APIRouter(prefix="/v1", tags=["geo-content-delivery-v1"])

API_ROOT = Path(__file__).resolve().parents[2]
AGENT_ARTIFACT_ROOT = API_ROOT / "private_artifacts" / "agent-runs"


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
    reviewer_ids = {review.reviewer_id for review in reviews if review.reviewer_id is not None}
    reviewer_names = {
        reviewer.id: reviewer.name
        for reviewer in db.scalars(select(User).where(User.id.in_(reviewer_ids or {-1})))
    }
    for review in reviews:
        review.reviewer_name = reviewer_names.get(review.reviewer_id)
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
    if payload.verdict == "approved" and unverified_ids:
        raise HTTPException(
            status_code=409,
            detail="未核验主张不能随稿批准；请退回并生成删除或补证后的新版本",
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
        approved_variant_ids = {
            review.subject_id
            for review in db.scalars(
                select(GeoContentReview).where(
                    GeoContentReview.workspace_id == workspace_id,
                    GeoContentReview.subject_type == "platform_variant",
                    GeoContentReview.verdict == "approved",
                )
            )
        }
        approved_variant_ids.update(variants_by_key[key].id for key in platform_keys)
        asset.status = "approved" if all(variant.id in approved_variant_ids for variant in variants) else "draft"
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
        if variant.image_manifest:
            variant.image_manifest = [
                {
                    **item,
                    "review_status": (
                        "approved" if payload.verdict == "approved" else "changes_requested"
                    ),
                    "reviewed_by_user_id": user.id,
                    "reviewed_at": datetime.now(timezone.utc).isoformat(),
                }
                for item in variant.image_manifest
            ]
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
    db.flush()
    _synchronize_article_action_truth(
        db,
        action,
        actor_user_id=user.id,
        trigger="content_review_decided",
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


@router.patch(
    "/workspaces/{workspace_id}/platform-variants/{variant_id}",
    response_model=PlatformVariantRead,
)
def update_platform_variant(
    workspace_id: int,
    variant_id: int,
    payload: PlatformVariantUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    variant = scoped_or_404(db, GeoPlatformVariant, workspace_id, variant_id)
    asset = scoped_or_404(db, GeoContentAsset, workspace_id, variant.content_asset_id)
    brief = scoped_or_404(db, GeoContentBrief, workspace_id, asset.brief_id)
    action = scoped_or_404(db, GeoOptimizationAction, workspace_id, brief.action_id)

    started_distribution = db.scalar(
        select(GeoDistributionTarget.id).where(
            GeoDistributionTarget.platform_variant_id == variant.id
        )
    )
    approved_review = db.scalar(
        select(GeoContentReview.id).where(
            GeoContentReview.workspace_id == workspace_id,
            GeoContentReview.subject_type == "platform_variant",
            GeoContentReview.subject_id == variant.id,
            GeoContentReview.verdict == "approved",
        )
    )
    if started_distribution or approved_review:
        raise HTTPException(
            status_code=409,
            detail="Approved or distributed drafts cannot be edited; generate a new version instead",
        )

    normalized = {
        "title": payload.title.strip(),
        "summary": payload.summary.strip(),
        "body_markdown": payload.body_markdown.strip(),
        "tags": list(dict.fromkeys(tag.strip() for tag in payload.tags if tag.strip())),
        "category": payload.category.strip() if payload.category and payload.category.strip() else None,
    }
    if not all(normalized[key] for key in ("title", "summary", "body_markdown")):
        raise HTTPException(status_code=422, detail="Title, summary, and body are required")

    if any(
        normalized[key] != getattr(variant, key)
        for key in ("title", "summary", "body_markdown")
    ):
        raise HTTPException(
            status_code=409,
            detail="平台正文不能在审核外直接改写；请退回并生成可重新核验的新版本",
        )

    previous_fingerprint = variant.content_fingerprint
    content_fingerprint = sha256(
        json.dumps(
            {
                "platform_key": variant.platform_key,
                **normalized,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    variant.title = normalized["title"]
    variant.summary = normalized["summary"]
    variant.body_markdown = normalized["body_markdown"]
    variant.tags = normalized["tags"]
    variant.category = normalized["category"]
    variant.content_fingerprint = content_fingerprint
    variant.status = "ready"
    variant.adaptation_contract = {
        **(variant.adaptation_contract or {}),
        "manual_edit": {
            "edited_at": datetime.now(timezone.utc).isoformat(),
            "editor_user_id": user.id,
            "previous_content_fingerprint": previous_fingerprint,
            "source_asset_fingerprint": asset.content_fingerprint,
        },
    }
    db.add(
        GeoActionEvent(
            workspace_id=workspace_id,
            action_id=action.id,
            event_type="platform_variant_edited",
            from_stage=action.stage,
            to_stage=action.stage,
            actor_type="user",
            actor_user_id=user.id,
            detail={
                "asset_id": asset.id,
                "variant_id": variant.id,
                "platform_key": variant.platform_key,
                "previous_content_fingerprint": previous_fingerprint,
                "content_fingerprint": content_fingerprint,
            },
        )
    )
    db.commit()
    db.refresh(variant)
    return variant


def _distribution_read(db: Session, run: GeoDistributionRun) -> dict:
    targets = list(
        db.scalars(
            select(GeoDistributionTarget)
            .where(GeoDistributionTarget.distribution_run_id == run.id)
            .order_by(GeoDistributionTarget.id.asc())
        )
    )
    return {"id": run.id, "targets": targets, **run.__dict__}


def _synchronize_article_action_truth(
    db: Session,
    action: GeoOptimizationAction | None,
    *,
    actor_user_id: int | None,
    trigger: str,
) -> list[dict]:
    """Keep the action-target projection aligned with durable content evidence."""

    if action is None:
        return []
    previous_stage = action.stage
    changes = v2_synchronize_article_action_targets(db, action)
    if changes:
        db.add(
            GeoActionEvent(
                workspace_id=action.workspace_id,
                action_id=action.id,
                event_type="action_target_truth_synchronized",
                from_stage=previous_stage,
                to_stage=action.stage,
                actor_type="system",
                actor_user_id=actor_user_id,
                detail={"trigger": trigger, "changes": changes},
            )
        )
    return changes


def _record_verified_distribution_publication(
    db: Session,
    *,
    run: GeoDistributionRun,
    distribution_target: GeoDistributionTarget,
    public_url: str,
    verification: dict,
    user_id: int,
) -> GeoActionCompletionEvidence | None:
    """Bridge a verified public distribution result into the action evidence ledger."""

    if not run.action_id:
        return None
    action_target = db.scalar(
        select(GeoActionTarget).where(
            GeoActionTarget.action_id == run.action_id,
            GeoActionTarget.target_type == "platform",
            GeoActionTarget.platform_key == distribution_target.platform_key,
        )
    )
    if action_target is None:
        return None
    idempotency_key = f"distribution-publication:{run.id}:{distribution_target.id}"
    existing = db.scalar(
        select(GeoActionCompletionEvidence).where(
            GeoActionCompletionEvidence.workspace_id == run.workspace_id,
            GeoActionCompletionEvidence.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing
    observed_sha = str(verification.get("sha256") or "")
    if len(observed_sha) != 64:
        observed_sha = sha256(
            json.dumps(verification, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
    now = datetime.now(timezone.utc)
    evidence = GeoActionCompletionEvidence(
        workspace_id=run.workspace_id,
        action_id=run.action_id,
        target_id=action_target.id,
        evidence_type="public_url",
        source_url=public_url,
        artifact_uri=None,
        sha256=observed_sha,
        verification_status="verified",
        detail={
            "source": "distribution_human_publication",
            "distribution_run_id": run.id,
            "distribution_target_id": distribution_target.id,
            "verification": verification,
            "final_action_clicked": False,
        },
        submitted_by_user_id=user_id,
        verified_by_user_id=user_id,
        submitted_at=now,
        verified_at=now,
        supersedes_evidence_id=None,
        idempotency_key=idempotency_key,
    )
    db.add(evidence)
    db.flush()
    action_target.verified_at = now
    action_target.completed_at = now
    action_target.completed_by_user_id = user_id
    return evidence


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
                    waiting_human_reason="等待用户在当前浏览器中打开 GEO 文章助手并确认写入。",
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
        db.flush()
        _synchronize_article_action_truth(
            db,
            action,
            actor_user_id=user.id,
            trigger="distribution_targets_extended",
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
                    else "等待用户在当前浏览器中打开 GEO 文章助手并确认写入。"
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
    db.flush()
    _synchronize_article_action_truth(
        db,
        action,
        actor_user_id=user.id,
        trigger="distribution_run_created",
    )
    db.commit()
    db.refresh(run)
    return _distribution_read(db, run)


ARTICLE_ASSISTANT_PROTOCOL = "geo-article-assistant.v1"
ARTICLE_ASSISTANT_TASK_TTL = timedelta(minutes=10)
ARTICLE_ASSISTANT_PLATFORMS = {
    "wechat", "zhihu", "juejin", "51cto", "csdn", "bilibili", "baijiahao",
    "weibo", "yuque", "douban", "sohu", "xueqiu", "cnblogs", "oschina",
    "segmentfault", "imooc", "woshipm", "eastmoney",
}


def _article_assistant_task_targets(
    db: Session, run: GeoDistributionRun
) -> tuple[list[dict], str]:
    if not run.content_asset_id:
        raise HTTPException(status_code=409, detail="当前任务没有可写入的已审核内容")
    targets = list(
        db.scalars(
            select(GeoDistributionTarget)
            .where(GeoDistributionTarget.distribution_run_id == run.id)
            .order_by(GeoDistributionTarget.id)
        )
    )
    task_targets: list[dict] = []
    for target in targets:
        if target.platform_key not in ARTICLE_ASSISTANT_PLATFORMS:
            continue
        if target.draft_readback_status in {"draft_saved", "awaiting_human_confirmation"}:
            continue
        variant = db.get(GeoPlatformVariant, target.platform_variant_id)
        if (
            variant is None
            or variant.workspace_id != run.workspace_id
            or variant.content_asset_id != run.content_asset_id
            or variant.platform_key != target.platform_key
            or variant.status != "approved"
        ):
            raise HTTPException(
                status_code=409,
                detail=f"{target.platform_key} 平台稿不再是已审核版本，请重新审核",
            )
        task_targets.append(
            {
                "target_id": target.id,
                "platform_key": target.platform_key,
                "platform_variant_id": variant.id,
                "title": variant.title,
                "summary": variant.summary,
                "body_markdown": variant.body_markdown,
                "tags": list(variant.tags or []),
                "category": variant.category,
                "image_manifest": list(variant.image_manifest or []),
                "content_fingerprint": variant.content_fingerprint,
            }
        )
    if not task_targets:
        raise HTTPException(status_code=409, detail="当前没有需要写入的已审核平台稿")
    fingerprint_payload = [
        {
            "platform_key": item["platform_key"],
            "platform_variant_id": item["platform_variant_id"],
            "content_fingerprint": item["content_fingerprint"],
            "media": [
                {
                    "artifact_id": media.get("artifact_id"),
                    "sha256": media.get("sha256"),
                    "review_status": media.get("review_status"),
                    "placement": media.get("placement"),
                    "caption": media.get("caption"),
                }
                for media in item.get("image_manifest") or []
            ],
        }
        for item in task_targets
    ]
    fingerprint = sha256(
        json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return task_targets, fingerprint


@router.post(
    "/workspaces/{workspace_id}/distribution-runs/{run_id}/assistant-task",
    response_model=ArticleAssistantTaskRead,
)
def issue_article_assistant_task(
    workspace_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    run = scoped_or_404(db, GeoDistributionRun, workspace_id, run_id)
    task_targets, content_fingerprint = _article_assistant_task_targets(db, run)
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + ARTICLE_ASSISTANT_TASK_TTL
    task_token = secrets.token_urlsafe(32)
    run.assistant_protocol_version = ARTICLE_ASSISTANT_PROTOCOL
    run.assistant_task_nonce_hash = sha256(task_token.encode()).hexdigest()
    run.assistant_task_expires_at = expires_at
    run.assistant_content_fingerprint = content_fingerprint
    run.assistant_task_issued_at = issued_at
    run.assistant_operator_user_id = user.id
    db.add(
        GeoActionEvent(
            workspace_id=workspace_id,
            action_id=run.action_id,
            event_type="geo_article_assistant_task_issued",
            from_stage=run.stage,
            to_stage=run.stage,
            actor_type="user",
            actor_user_id=user.id,
            detail={
                "distribution_run_id": run.id,
                "protocol_version": ARTICLE_ASSISTANT_PROTOCOL,
                "content_fingerprint": content_fingerprint,
                "platform_keys": [item["platform_key"] for item in task_targets],
                "expires_at": expires_at.isoformat(),
                "final_action_clicked": False,
            },
        )
    )
    db.flush()
    _synchronize_article_action_truth(
        db,
        db.get(GeoOptimizationAction, run.action_id) if run.action_id else None,
        actor_user_id=user.id,
        trigger="article_assistant_task_issued",
    )
    db.commit()
    # The extension receives only a short-lived, run-scoped media URL.  The
    # browser session cookie is neither exposed to nor required by the
    # extension, and pending/unreviewed images never get a delivery URL.
    delivery_targets: list[dict] = []
    for target in task_targets:
        delivered_manifest: list[dict] = []
        for media in target.get("image_manifest") or []:
            delivered = dict(media)
            artifact_id = int(delivered.get("artifact_id") or 0)
            if (
                artifact_id > 0
                and delivered.get("review_status") == "approved"
                and delivered.get("quality_gate") == "passed"
            ):
                delivered["content_path"] = (
                    f"/api/geo/{workspace_id}/distribution-runs/{run.id}"
                    f"/assistant-media/{artifact_id}?task_token={task_token}"
                )
            delivered_manifest.append(delivered)
        delivery_targets.append(
            {**target, "image_manifest": delivered_manifest}
        )
    return {
        "protocol_version": ARTICLE_ASSISTANT_PROTOCOL,
        "task_token": task_token,
        "run_id": run.id,
        "workspace_id": workspace_id,
        "action_id": run.action_id,
        "content_asset_id": run.content_asset_id,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "content_fingerprint": content_fingerprint,
        "targets": delivery_targets,
    }


@router.get(
    "/workspaces/{workspace_id}/distribution-runs/{run_id}/assistant-media/{artifact_id}",
    response_class=FileResponse,
)
def read_article_assistant_media(
    workspace_id: int,
    run_id: int,
    artifact_id: int,
    task_token: str = Query(min_length=20, max_length=200),
    db: Session = Depends(get_db),
):
    """Serve one reviewed image to the local draft-only browser extension.

    This deliberately uses the short-lived, one-time task credential rather
    than the user's session cookie.  The artifact must still be referenced by
    an approved variant in this exact distribution run.
    """

    run = db.get(GeoDistributionRun, run_id)
    if run is None or run.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Article assistant media not found")
    if not run.assistant_task_nonce_hash or not hmac.compare_digest(
        run.assistant_task_nonce_hash,
        sha256(task_token.encode()).hexdigest(),
    ):
        raise HTTPException(status_code=403, detail="Article assistant task credential is invalid")
    now = datetime.now(timezone.utc)
    if not run.assistant_task_expires_at or _as_utc(run.assistant_task_expires_at) <= now:
        raise HTTPException(status_code=410, detail="Article assistant task has expired")

    artifact = db.get(GeoAgentArtifact, artifact_id)
    if artifact is None or artifact.workspace_id != workspace_id or artifact.artifact_kind not in {
        "official_page_screenshot",
        "generated_article_image",
        "licensed_web_image",
    }:
        raise HTTPException(status_code=404, detail="Article assistant media not found")
    variant_ids = {
        int(value)
        for value in db.scalars(
            select(GeoDistributionTarget.platform_variant_id).where(
                GeoDistributionTarget.distribution_run_id == run.id
            )
        )
        if value
    }
    variants = list(
        db.scalars(
            select(GeoPlatformVariant).where(
                GeoPlatformVariant.id.in_(variant_ids or {-1}),
                GeoPlatformVariant.status == "approved",
            )
        )
    )
    referenced = any(
        int(item.get("artifact_id") or 0) == artifact.id
        and item.get("review_status") == "approved"
        and item.get("quality_gate") == "passed"
        for variant in variants
        for item in (variant.image_manifest or [])
    )
    if not referenced:
        raise HTTPException(status_code=404, detail="Reviewed article media not found")
    try:
        root = AGENT_ARTIFACT_ROOT.resolve(strict=True)
        artifact_path = Path(artifact.uri).resolve(strict=True)
        artifact_path.relative_to(root)
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="Article assistant media file not found") from None
    payload = artifact_path.read_bytes()
    if sha256(payload).hexdigest() != artifact.sha256:
        raise HTTPException(status_code=409, detail="Article assistant media integrity check failed")
    media_type = str((artifact.metadata_json or {}).get("media_type") or "image/png")
    if media_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise HTTPException(status_code=409, detail="Article assistant media type is invalid")
    return FileResponse(
        artifact_path,
        media_type=media_type,
        headers={"Cache-Control": "private, no-store", "ETag": f'"{artifact.sha256}"'},
    )


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
            raise HTTPException(status_code=409, detail="官网人工交付不接受 GEO 文章助手草稿结果")
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
        elif result.request_status == "failed":
            target.request_status = "failed"
            target.draft_readback_status = "failed"
            target.candidate_draft_url = None
            target.draft_url = None
            target.external_draft_id = None
            target.blocked_reason = (result.message or "GEO 文章助手未能保存草稿")[:2000]
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
    db.flush()
    _synchronize_article_action_truth(
        db,
        action,
        actor_user_id=user.id,
        trigger="distribution_client_results_recorded",
    )
    db.commit()
    db.refresh(run)
    return _distribution_read(db, run)


@router.post(
    "/workspaces/{workspace_id}/distribution-runs/{run_id}/assistant-results",
    response_model=DistributionRunRead,
)
def record_article_assistant_results(
    workspace_id: int,
    run_id: int,
    payload: ArticleAssistantClientResults,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    run = scoped_or_404(db, GeoDistributionRun, workspace_id, run_id)
    if run.assistant_protocol_version != payload.protocol_version:
        raise HTTPException(status_code=409, detail="GEO 文章助手协议版本不匹配，请刷新后重试")
    if run.assistant_operator_user_id != user.id:
        raise HTTPException(status_code=403, detail="本次草稿写入必须由发起人回传结果")
    if not run.assistant_task_nonce_hash or not hmac.compare_digest(
        run.assistant_task_nonce_hash, sha256(payload.task_token.encode()).hexdigest()
    ):
        raise HTTPException(status_code=409, detail="GEO 文章助手任务凭证无效或已使用")
    now = datetime.now(timezone.utc)
    if not run.assistant_task_expires_at or _as_utc(run.assistant_task_expires_at) <= now:
        raise HTTPException(status_code=409, detail="GEO 文章助手任务已过期，请重新发起")
    _, current_fingerprint = _article_assistant_task_targets(db, run)
    if (
        payload.content_fingerprint != run.assistant_content_fingerprint
        or current_fingerprint != run.assistant_content_fingerprint
    ):
        raise HTTPException(status_code=409, detail="已审核内容发生变化，本次草稿写入已取消")
    allowed_platforms = {
        target.platform_key
        for target in db.scalars(
            select(GeoDistributionTarget).where(GeoDistributionTarget.distribution_run_id == run.id)
        )
    }
    if any(result.platform_key not in allowed_platforms for result in payload.targets):
        raise HTTPException(status_code=422, detail="回传结果包含本次任务之外的平台")

    # One-time credential: consume it before recording the durable, auditable
    # per-platform outcomes. Browser cookies and account tokens never enter API.
    run.assistant_task_nonce_hash = None
    result = record_distribution_client_results(
        workspace_id,
        run_id,
        DistributionClientResults(targets=payload.targets),
        db,
        user,
    )
    return result


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
        "bilibili": "bilibili.com",
        "baijiahao": "baidu.com",
        "weibo": "weibo.com",
        "yuque": "yuque.com",
        "douban": "douban.com",
        "sohu": "sohu.com",
        "xueqiu": "xueqiu.com",
        "cnblogs": "cnblogs.com",
        "oschina": "oschina.net",
        "segmentfault": "segmentfault.com",
        "imooc": "imooc.com",
        "woshipm": "woshipm.com",
        "eastmoney": "eastmoney.com",
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
    db.flush()
    _synchronize_article_action_truth(
        db,
        action,
        actor_user_id=user.id,
        trigger="draft_readback_human_confirmed",
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

    public_platforms = {
        "zhihu": ("zhihu.com", "知乎"),
        "juejin": ("juejin.cn", "稀土掘金"),
        "csdn": ("csdn.net", "CSDN"),
        "51cto": ("51cto.com", "51CTO"),
        "bilibili": ("bilibili.com", "哔哩哔哩"),
        "baijiahao": ("baidu.com", "百家号"),
        "weibo": ("weibo.com", "微博"),
        "yuque": ("yuque.com", "语雀"),
        "douban": ("douban.com", "豆瓣"),
        "sohu": ("sohu.com", "搜狐号"),
        "xueqiu": ("xueqiu.com", "雪球"),
        "cnblogs": ("cnblogs.com", "博客园"),
        "oschina": ("oschina.net", "开源中国"),
        "segmentfault": ("segmentfault.com", "思否"),
        "imooc": ("imooc.com", "慕课手记"),
        "woshipm": ("woshipm.com", "人人都是产品经理"),
        "eastmoney": ("eastmoney.com", "东方财富"),
        "xiaohongshu": ("xiaohongshu.com", "小红书"),
    }
    if platform_key == "wechat":
        valid = host == "mp.weixin.qq.com"
        expected_label = "微信公众号"
    elif platform_key == "official_site":
        website_host = (urlsplit(workspace.website_url or "").hostname or "").lower().rstrip(".")
        if not website_host:
            raise HTTPException(status_code=422, detail="请先在设置中配置官网域名")
        valid = host == website_host or host.endswith(f".{website_host}")
        expected_label = "当前工作区官网"
    elif platform_key in public_platforms:
        expected_domain, expected_label = public_platforms[platform_key]
        valid = host_matches(expected_domain)
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
    _record_verified_distribution_publication(
        db,
        run=run,
        distribution_target=target,
        public_url=public_url,
        verification=verification,
        user_id=user.id,
    )
    _synchronize_article_action_truth(
        db,
        action,
        actor_user_id=user.id,
        trigger="human_publication_recorded",
    )
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
    if any(target.platform_key == "official_site" for target in targets):
        raise HTTPException(
            status_code=409,
            detail="官网稿不得通过文章同步助手或 MCP 请求写入",
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
    db.flush()
    _synchronize_article_action_truth(
        db,
        db.get(GeoOptimizationAction, run.action_id) if run.action_id else None,
        actor_user_id=user.id,
        trigger="distribution_mcp_requested",
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
    _synchronize_article_action_truth(
        db,
        db.get(GeoOptimizationAction, run.action_id) if run.action_id else None,
        actor_user_id=user.id,
        trigger="distribution_mcp_readback",
    )
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
    workspace = workspace_or_404(db, user, workspace_id)
    action = scoped_or_404(db, GeoOptimizationAction, workspace_id, action_id)
    brief = scoped_or_404(db, GeoContentBrief, workspace_id, brief_id)
    if brief.action_id != action_id:
        raise HTTPException(status_code=404, detail="Content brief not found")
    provider = db.get(LLMProvider, payload.provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="LLM provider not found")
    workspace_api_key = (
        get_workspace_secret(db, workspace_id, DEEPSEEK_API_KEY)
        if provider.provider_type == "deepseek_web_search"
        else None
    )
    diagnostic = diagnose_provider(provider, api_key_override=workspace_api_key)
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
        payload_json=geo_job_payload(
            workspace_id=workspace_id,
            company_id=workspace.company_id,
            actor_user_id=user.id,
            action_id=action_id,
            brief_id=brief_id,
            provider_id=provider.id,
            platform_key=payload.platform_key,
        ),
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
