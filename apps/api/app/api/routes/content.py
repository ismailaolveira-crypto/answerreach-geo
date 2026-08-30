import secrets
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import (
    CONTENT_ROLES,
    REVIEW_ROLES,
    get_project_or_404,
    require_project_access,
    require_roles,
)
from app.db.session import get_db
from app.core.config import get_settings
from app.models import (
    AnswerAnalysis,
    ArticleDraft,
    ArticleReview,
    AuditLog,
    CitationSource,
    ContentAsset,
    ContentAssetReview,
    CrawlResult,
    CrawlTask,
    DeliveryPackageAccessLog,
    DeliveryPackageShare,
    PlacementRecord,
    Project,
    ProjectStageGoal,
    SystemAlert,
    User,
)
from app.schemas.common import APIMessage
from app.schemas.content import (
    ArticleDraftGenerate,
    ArticleDraftRead,
    ArticleDraftUpdate,
    ArticleReviewCreate,
    ArticleReviewRead,
    ContentAssetCreate,
    ContentAssetBulkCreate,
    ContentAssetRead,
    ContentAssetReviewCreate,
    ContentAssetReviewRead,
    ContentAssetUpdate,
    HumanReviewDecision,
    DeliveryPackageAccessLogRead,
    DeliveryPackageShareCreate,
    DeliveryPackageShareRead,
    PublicDeliveryConfirmRequest,
    PublicDeliveryPackageRead,
    PlacementRecordCreate,
    PlacementImpactRead,
    PlacementRecordRead,
    PlacementRecordUpdate,
)
from app.schemas.project import ProjectStageGoalRead
from app.services.article_workflow import (
    decide_article_draft_review,
    decide_content_asset_review,
    generate_article_draft,
    revise_article_draft_from_review,
    review_article_draft,
    review_content_asset,
)
from app.services.audit import record_audit_log
from app.services.auth import consume_security_rate_limit
from app.services.content_remediation import create_content_asset_remediation_goals
from app.services.placement_impact_goals import create_placement_impact_goals
from app.services.project_goals import goal_suggested_actions
from app.services.workspace_secrets import decrypt_secret, encrypt_secret

router = APIRouter(
    prefix="/projects/{project_id}",
    tags=["content"],
    dependencies=[Depends(require_project_access)],
)

public_router = APIRouter(prefix="/public/delivery-packages", tags=["public-delivery"])

DELIVERABLE_STATUSES = {"ready", "delivered", "accepted"}


def get_draft_or_404(db: Session, project_id: int, draft_id: int) -> ArticleDraft:
    draft = db.get(ArticleDraft, draft_id)
    if draft is None or draft.project_id != project_id:
        raise HTTPException(status_code=404, detail="Article draft not found")
    return draft


def get_asset_or_404(db: Session, project_id: int, asset_id: int) -> ContentAsset:
    asset = db.get(ContentAsset, asset_id)
    if asset is None or asset.project_id != project_id:
        raise HTTPException(status_code=404, detail="Content asset not found")
    return asset


def get_placement_or_404(db: Session, project_id: int, placement_id: int) -> PlacementRecord:
    placement = db.get(PlacementRecord, placement_id)
    if placement is None or placement.project_id != project_id:
        raise HTTPException(status_code=404, detail="Placement record not found")
    return placement


def _stage_goal_for_placement(db: Session, project_id: int, placement_id: int) -> ProjectStageGoal | None:
    logs = db.scalars(
        select(AuditLog)
        .where(AuditLog.project_id == project_id)
        .where(
            AuditLog.action.in_(
                [
                    "stage_goal.action.create_placement",
                    "stage_goal.action.approve_and_create_placement",
                    "stage_goal.action.publish_prepare_delivery",
                ]
            )
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    )
    for log in logs:
        log_placement_id = log.detail_json.get("placement_id") or log.resource_id
        if int(log_placement_id or 0) != placement_id:
            continue
        goal_id = log.detail_json.get("stage_goal_id")
        if goal_id:
            goal = db.get(ProjectStageGoal, int(goal_id))
            if goal is not None and goal.project_id == project_id:
                return goal
    return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _is_share_valid(share: DeliveryPackageShare) -> bool:
    if share.status != "active":
        return False
    if share.expires_at is None:
        return True
    expires_at = share.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at > _now_utc()


def _get_share_or_404(db: Session, token: str) -> DeliveryPackageShare:
    share = db.scalar(select(DeliveryPackageShare).where(DeliveryPackageShare.token == token))
    if share is None or not _is_share_valid(share):
        raise HTTPException(status_code=404, detail="Delivery package not found")
    return share


def _is_customer_deliverable(placement: PlacementRecord) -> bool:
    return placement.visibility == "customer_visible" and placement.delivery_status in DELIVERABLE_STATUSES


def _public_export_url(token: str, placement_id: int, export_type: str) -> str:
    return f"/api/public/delivery-packages/{token}/placements/{placement_id}/export/{export_type}"


def _record_delivery_access(
    db: Session,
    share: DeliveryPackageShare,
    event_type: str,
    *,
    placement_id: int | None = None,
    actor_name: str | None = None,
    comment: str | None = None,
    detail: dict | None = None,
) -> DeliveryPackageAccessLog:
    now = _now_utc()
    share.last_accessed_at = now
    if event_type in {"view_package", "export_markdown", "export_pdf"}:
        existing = db.scalar(
            select(DeliveryPackageAccessLog)
            .where(
                DeliveryPackageAccessLog.share_id == share.id,
                DeliveryPackageAccessLog.placement_id == placement_id,
                DeliveryPackageAccessLog.event_type == event_type,
                DeliveryPackageAccessLog.created_at >= now - timedelta(minutes=5),
            )
            .order_by(DeliveryPackageAccessLog.created_at.desc())
        )
        if existing is not None:
            return existing
    access_log = DeliveryPackageAccessLog(
        share_id=share.id,
        project_id=share.project_id,
        placement_id=placement_id,
        event_type=event_type,
        actor_name=actor_name,
        comment=comment,
        detail_json=detail or {},
    )
    db.add(access_log)
    return access_log


def _consume_public_delivery_rate(
    db: Session,
    *,
    share_id: int,
    scope: str,
    limit: int,
) -> None:
    retry_after = consume_security_rate_limit(
        db,
        scope=scope,
        identity=str(share_id),
        limit=limit,
        window=timedelta(hours=1),
    )
    db.commit()
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="公开交付访问过于频繁，请稍后重试",
            headers={"Retry-After": str(retry_after)},
        )


def _share_read(share: DeliveryPackageShare, *, reveal_confirmation: bool = False) -> DeliveryPackageShareRead:
    confirmation_token = None
    if reveal_confirmation and share.confirmation_token_encrypted:
        confirmation_token = decrypt_secret(share.confirmation_token_encrypted)
    return DeliveryPackageShareRead.model_validate(share).model_copy(
        update={"confirmation_token": confirmation_token}
    )


def _public_deliverable_item(project_id: int, token: str, placement: PlacementRecord, db: Session) -> dict:
    impact = get_placement_impact(project_id, placement.id, db)
    return {
        "placement": PlacementRecordRead.model_validate(placement).model_dump(mode="json"),
        "summary": impact.summary,
        "recommendations": impact.recommendations,
        "review_report": impact.review_report,
        "exports": {
            "markdown": _public_export_url(token, placement.id, "markdown"),
            "pdf": _public_export_url(token, placement.id, "pdf"),
        },
    }


def _public_delivery_package_payload(share: DeliveryPackageShare, db: Session) -> PublicDeliveryPackageRead:
    project = db.get(Project, share.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Delivery package not found")
    placements = list(
        db.scalars(
            select(PlacementRecord)
            .where(PlacementRecord.project_id == project.id)
            .where(PlacementRecord.status == "published")
            .where(PlacementRecord.visibility == "customer_visible")
            .where(PlacementRecord.delivery_status.in_(DELIVERABLE_STATUSES))
            .order_by(PlacementRecord.published_at.desc(), PlacementRecord.created_at.desc())
        )
    )
    return PublicDeliveryPackageRead(
        project={"id": project.id, "name": project.name, "description": project.description},
        share={
            "name": share.name,
            "status": share.status,
            "expires_at": share.expires_at.isoformat() if share.expires_at else None,
            "last_accessed_at": share.last_accessed_at.isoformat() if share.last_accessed_at else None,
        },
        deliverables=[
            _public_deliverable_item(project.id, share.token, placement, db)
            for placement in placements
            if _is_customer_deliverable(placement)
        ],
    )


@router.get("/content-assets", response_model=list[ContentAssetRead])
def list_content_assets(project_id: int, db: Session = Depends(get_db)) -> list[ContentAsset]:
    get_project_or_404(db, project_id)
    return list(
        db.scalars(
            select(ContentAsset)
            .where(ContentAsset.project_id == project_id)
            .order_by(ContentAsset.created_at.desc())
        )
    )


@router.post("/content-assets", response_model=ContentAssetRead, status_code=201)
def create_content_asset(
    project_id: int,
    payload: ContentAssetCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CONTENT_ROLES)),
) -> ContentAsset:
    project = get_project_or_404(db, project_id)
    data = payload.model_dump()
    data["project_id"] = project_id
    data["company_id"] = project.company_id
    asset = ContentAsset(**data)
    db.add(asset)
    db.flush()
    record_audit_log(
        db,
        user=user,
        action="content_asset.create",
        resource_type="content_asset",
        resource_id=asset.id,
        project_id=project.id,
        company_id=project.company_id,
        detail={"content_type": asset.content_type, "title": asset.title},
    )
    db.commit()
    db.refresh(asset)
    return asset


@router.post("/content-assets/bulk", response_model=list[ContentAssetRead], status_code=201)
def bulk_create_content_assets(
    project_id: int,
    payload: ContentAssetBulkCreate,
    db: Session = Depends(get_db),
    _user: object = Depends(require_roles(*CONTENT_ROLES)),
) -> list[ContentAsset]:
    project = get_project_or_404(db, project_id)
    assets = []
    for item in payload.items:
        data = item.model_dump()
        data["project_id"] = project_id
        data["company_id"] = project.company_id
        assets.append(ContentAsset(**data))
    db.add_all(assets)
    db.commit()
    for asset in assets:
        db.refresh(asset)
    return assets


@router.get("/content-assets/{asset_id}", response_model=ContentAssetRead)
def get_content_asset(project_id: int, asset_id: int, db: Session = Depends(get_db)) -> ContentAsset:
    return get_asset_or_404(db, project_id, asset_id)


@router.patch("/content-assets/{asset_id}", response_model=ContentAssetRead)
def update_content_asset(
    project_id: int,
    asset_id: int,
    payload: ContentAssetUpdate,
    db: Session = Depends(get_db),
    _user: object = Depends(require_roles(*CONTENT_ROLES)),
) -> ContentAsset:
    asset = get_asset_or_404(db, project_id, asset_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(asset, field, value)
    db.commit()
    db.refresh(asset)
    return asset


@router.delete("/content-assets/{asset_id}", response_model=APIMessage)
def delete_content_asset(
    project_id: int,
    asset_id: int,
    db: Session = Depends(get_db),
    _user: object = Depends(require_roles(*CONTENT_ROLES)),
) -> APIMessage:
    asset = get_asset_or_404(db, project_id, asset_id)
    db.delete(asset)
    db.commit()
    return APIMessage(message="Content asset deleted")


@router.post(
    "/content-assets/{asset_id}/reviews", response_model=ContentAssetReviewRead, status_code=201
)
def create_content_asset_review(
    project_id: int,
    asset_id: int,
    payload: ContentAssetReviewCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*REVIEW_ROLES)),
) -> ContentAssetReview:
    asset = get_asset_or_404(db, project_id, asset_id)
    review = review_content_asset(db, asset, payload.review_type)
    record_audit_log(
        db,
        user=user,
        action="content_asset.review",
        resource_type="content_asset_review",
        resource_id=review.id,
        project_id=project_id,
        company_id=asset.company_id,
        detail={"asset_id": asset.id, "total_score": review.total_score, "grade": review.grade},
    )
    db.commit()
    return review


@router.post(
    "/content-assets/{asset_id}/human-review",
    response_model=ContentAssetReviewRead,
    status_code=201,
)
def decide_content_asset_human_review(
    project_id: int,
    asset_id: int,
    payload: HumanReviewDecision,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*REVIEW_ROLES)),
) -> ContentAssetReview:
    asset = get_asset_or_404(db, project_id, asset_id)
    review = decide_content_asset_review(
        db,
        asset,
        reviewer_id=user.id,
        decision=payload.decision,
        comment=payload.comment,
    )
    record_audit_log(
        db,
        user=user,
        action="content_asset.human_review",
        resource_type="content_asset_review",
        resource_id=review.id,
        project_id=project_id,
        company_id=asset.company_id,
        detail={"asset_id": asset.id, "decision": payload.decision, "comment": payload.comment},
    )
    db.commit()
    db.refresh(review)
    return review


@router.get("/content-assets/{asset_id}/reviews", response_model=list[ContentAssetReviewRead])
def list_content_asset_reviews(
    project_id: int, asset_id: int, db: Session = Depends(get_db)
) -> list[ContentAssetReview]:
    get_asset_or_404(db, project_id, asset_id)
    return list(
        db.scalars(
            select(ContentAssetReview)
            .where(ContentAssetReview.content_asset_id == asset_id)
            .order_by(ContentAssetReview.created_at.desc())
        )
    )


@router.post("/content-assets/remediation-goals", response_model=list[ProjectStageGoalRead])
def create_content_asset_remediation_stage_goals(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CONTENT_ROLES)),
) -> list[ProjectStageGoalRead]:
    project = get_project_or_404(db, project_id)
    goals = create_content_asset_remediation_goals(db, project)
    for goal in goals:
        record_audit_log(
            db,
            user=user,
            action="content_asset.remediation_goal.create",
            resource_type="project_stage_goal",
            resource_id=goal.id,
            project_id=project.id,
            company_id=project.company_id,
            detail={"title": goal.title, "metric_key": goal.metric_key},
        )
    db.commit()
    return [
        ProjectStageGoalRead.model_validate(goal).model_copy(
            update={"suggested_actions": goal_suggested_actions(goal, "unknown")}
        )
        for goal in goals
    ]


@router.get("/placements", response_model=list[PlacementRecordRead])
def list_placement_records(project_id: int, db: Session = Depends(get_db)) -> list[PlacementRecord]:
    get_project_or_404(db, project_id)
    return list(
        db.scalars(
            select(PlacementRecord)
            .where(PlacementRecord.project_id == project_id)
            .order_by(PlacementRecord.created_at.desc())
        )
    )


@router.post("/placements", response_model=PlacementRecordRead, status_code=201)
def create_placement_record(
    project_id: int,
    payload: PlacementRecordCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CONTENT_ROLES)),
) -> PlacementRecord:
    project = get_project_or_404(db, project_id)
    placement = PlacementRecord(project_id=project_id, **payload.model_dump())
    db.add(placement)
    db.flush()
    record_audit_log(
        db,
        user=user,
        action="placement.create",
        resource_type="placement_record",
        resource_id=placement.id,
        project_id=project.id,
        company_id=project.company_id,
        detail={"channel": placement.channel, "target_url": placement.target_url},
    )
    db.commit()
    db.refresh(placement)
    return placement


@router.patch("/placements/{placement_id}", response_model=PlacementRecordRead)
def update_placement_record(
    project_id: int,
    placement_id: int,
    payload: PlacementRecordUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CONTENT_ROLES)),
) -> PlacementRecord:
    project = get_project_or_404(db, project_id)
    placement = get_placement_or_404(db, project_id, placement_id)
    changed_fields = payload.model_dump(exclude_unset=True)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(placement, field, value)
    if changed_fields:
        record_audit_log(
            db,
            user=user,
            action="placement.update",
            resource_type="placement_record",
            resource_id=placement.id,
            project_id=project.id,
            company_id=project.company_id,
            detail={"changed_fields": sorted(changed_fields.keys())},
        )
    db.commit()
    db.refresh(placement)
    return placement


@router.delete("/placements/{placement_id}", response_model=APIMessage)
def delete_placement_record(
    project_id: int,
    placement_id: int,
    db: Session = Depends(get_db),
    _user: object = Depends(require_roles(*CONTENT_ROLES)),
) -> APIMessage:
    placement = get_placement_or_404(db, project_id, placement_id)
    db.delete(placement)
    db.commit()
    return APIMessage(message="Placement record deleted")


@router.get("/delivery-shares", response_model=list[DeliveryPackageShareRead])
def list_delivery_package_shares(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(*CONTENT_ROLES)),
) -> list[DeliveryPackageShareRead]:
    get_project_or_404(db, project_id)
    shares = list(
        db.scalars(
            select(DeliveryPackageShare)
            .where(DeliveryPackageShare.project_id == project_id)
            .order_by(DeliveryPackageShare.created_at.desc())
        )
    )
    return [_share_read(share, reveal_confirmation=True) for share in shares]


@router.post("/delivery-shares", response_model=DeliveryPackageShareRead, status_code=201)
def create_delivery_package_share(
    project_id: int,
    payload: DeliveryPackageShareCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CONTENT_ROLES)),
) -> DeliveryPackageShareRead:
    project = get_project_or_404(db, project_id)
    confirmation_token = secrets.token_urlsafe(24)
    share = DeliveryPackageShare(
        project_id=project_id,
        token=secrets.token_urlsafe(24),
        name=payload.name,
        expires_at=payload.expires_at,
        created_by_user_id=user.id,
        confirmation_token_encrypted=encrypt_secret(confirmation_token),
    )
    db.add(share)
    db.flush()
    record_audit_log(
        db,
        user=user,
        action="delivery_share.create",
        resource_type="delivery_package_share",
        resource_id=share.id,
        project_id=project.id,
        company_id=project.company_id,
        detail={"name": share.name, "expires_at": share.expires_at.isoformat() if share.expires_at else None},
    )
    db.commit()
    db.refresh(share)
    return _share_read(share, reveal_confirmation=True)


@router.patch("/delivery-shares/{share_id}/revoke", response_model=DeliveryPackageShareRead)
def revoke_delivery_package_share(
    project_id: int,
    share_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CONTENT_ROLES)),
) -> DeliveryPackageShare:
    project = get_project_or_404(db, project_id)
    share = db.get(DeliveryPackageShare, share_id)
    if share is None or share.project_id != project_id:
        raise HTTPException(status_code=404, detail="Delivery share not found")
    share.status = "revoked"
    record_audit_log(
        db,
        user=user,
        action="delivery_share.revoke",
        resource_type="delivery_package_share",
        resource_id=share.id,
        project_id=project.id,
        company_id=project.company_id,
        detail={"share_id": share.id, "token_fingerprint": sha256(share.token.encode()).hexdigest()[:12]},
    )
    db.commit()
    db.refresh(share)
    return share


@router.post(
    "/delivery-shares/{share_id}/confirmation-token",
    response_model=DeliveryPackageShareRead,
)
def rotate_delivery_confirmation_token(
    project_id: int,
    share_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CONTENT_ROLES)),
) -> DeliveryPackageShareRead:
    project = get_project_or_404(db, project_id)
    share = db.get(DeliveryPackageShare, share_id)
    if share is None or share.project_id != project_id:
        raise HTTPException(status_code=404, detail="Delivery share not found")
    confirmation_token = secrets.token_urlsafe(24)
    share.confirmation_token_encrypted = encrypt_secret(confirmation_token)
    record_audit_log(
        db,
        user=user,
        action="delivery_share.confirmation_rotated",
        resource_type="delivery_package_share",
        resource_id=share.id,
        project_id=project.id,
        company_id=project.company_id,
        detail={"share_id": share.id, "secret_values_omitted": True},
    )
    db.commit()
    db.refresh(share)
    return _share_read(share, reveal_confirmation=True)


@router.get("/delivery-shares/access-logs", response_model=list[DeliveryPackageAccessLogRead])
def list_delivery_package_access_logs(
    project_id: int, db: Session = Depends(get_db)
) -> list[DeliveryPackageAccessLog]:
    get_project_or_404(db, project_id)
    return list(
        db.scalars(
            select(DeliveryPackageAccessLog)
            .where(DeliveryPackageAccessLog.project_id == project_id)
            .order_by(DeliveryPackageAccessLog.created_at.desc())
            .limit(100)
        )
    )


def _metric_window(db: Session, project_id: int, before: bool, baseline) -> dict[str, float | int]:
    op = CrawlResult.collected_at < baseline if before else CrawlResult.collected_at >= baseline
    total = (
        db.scalar(
            select(func.count())
            .select_from(CrawlResult)
            .where(CrawlResult.project_id == project_id)
            .where(op)
        )
        or 0
    )
    mentions = (
        db.scalar(
            select(func.count())
            .select_from(AnswerAnalysis)
            .join(CrawlResult, CrawlResult.id == AnswerAnalysis.crawl_result_id)
            .where(CrawlResult.project_id == project_id)
            .where(op)
            .where(AnswerAnalysis.company_mentioned.is_(True))
        )
        or 0
    )
    recommendations = (
        db.scalar(
            select(func.count())
            .select_from(AnswerAnalysis)
            .join(CrawlResult, CrawlResult.id == AnswerAnalysis.crawl_result_id)
            .where(CrawlResult.project_id == project_id)
            .where(op)
            .where(AnswerAnalysis.company_recommended.is_(True))
        )
        or 0
    )
    denominator = total or 1
    return {
        "total_answers": total,
        "company_mentions": mentions,
        "company_recommendations": recommendations,
        "company_mention_rate": round(mentions / denominator, 4),
        "company_recommendation_rate": round(recommendations / denominator, 4),
    }


@router.get("/placements/{placement_id}/impact", response_model=PlacementImpactRead)
def get_placement_impact(
    project_id: int, placement_id: int, db: Session = Depends(get_db)
) -> PlacementImpactRead:
    project = get_project_or_404(db, project_id)
    placement = get_placement_or_404(db, project_id, placement_id)
    baseline = placement.published_at or placement.created_at
    before = _metric_window(db, project_id, True, baseline)
    after = _metric_window(db, project_id, False, baseline)

    source_domain = urlparse(placement.target_url).netloc if placement.target_url else None
    source_after_appearances = 0
    if source_domain:
        source_after_appearances = (
            db.scalar(
                select(func.count())
                .select_from(CitationSource)
                .join(CrawlResult, CrawlResult.id == CitationSource.crawl_result_id)
                .where(CrawlResult.project_id == project_id)
                .where(CrawlResult.collected_at >= baseline)
                .where(CitationSource.source_domain == source_domain)
            )
            or 0
        )

    mention_delta = after["company_mention_rate"] - before["company_mention_rate"]
    recommendation_delta = after["company_recommendation_rate"] - before["company_recommendation_rate"]
    recommendations = []
    if after["total_answers"] < 5:
        recommendations.append("投放后样本量偏少，建议继续采集至少 5-10 轮再判断趋势。")
    if source_domain and source_after_appearances == 0:
        recommendations.append("投放域名尚未在投放后 AI 答案信源中出现，建议检查页面可抓取性和内容结构。")
    if mention_delta <= 0:
        recommendations.append("企业提及率暂未提升，建议补充目标问题直答型内容并增加权威信源。")
    if recommendation_delta <= 0:
        recommendations.append("企业推荐率暂未提升，建议强化案例、资质、对比理由和适用场景。")
    if not recommendations:
        recommendations.append("投放后指标有正向变化，建议继续监测并扩展相似选题。")

    review_alerts = list(
        db.scalars(
            select(SystemAlert)
            .where(SystemAlert.project_id == project_id)
            .where(SystemAlert.alert_type == "placement.review_due")
            .order_by(SystemAlert.created_at.desc())
            .limit(20)
        )
    )
    review_alert = next(
        (
            alert
            for alert in review_alerts
            if int(alert.detail_json.get("placement_id") or 0) == placement.id
        ),
        None,
    )
    review_crawl_task_id = None
    review_queue_job_id = None
    review_task_status = None
    if review_alert is not None:
        review_crawl_task_id = review_alert.detail_json.get("review_crawl_task_id")
        review_queue_job_id = review_alert.detail_json.get("review_queue_job_id")
        if review_crawl_task_id:
            review_task = db.get(CrawlTask, int(review_crawl_task_id))
            review_task_status = review_task.status if review_task else None

    after_sample_size = int(after["total_answers"] or 0)
    before_sample_size = int(before["total_answers"] or 0)
    mention_delta = round(mention_delta, 4)
    recommendation_delta = round(recommendation_delta, 4)
    if after_sample_size < 5:
        review_status = "insufficient_sample"
        conclusion = "复盘样本量偏少，暂不建议做强结论。"
    elif mention_delta > 0 and recommendation_delta > 0:
        review_status = "positive"
        conclusion = "投放后企业提及率和推荐率均有提升，投放动作呈正向效果。"
    elif mention_delta > 0 or recommendation_delta > 0:
        review_status = "mixed"
        conclusion = "投放后部分核心指标改善，建议继续补强信源和内容结构。"
    else:
        review_status = "needs_optimization"
        conclusion = "投放后核心指标暂未改善，需要复查选题、信源质量和页面可抓取性。"

    review_report = {
        "status": review_status,
        "conclusion": conclusion,
        "project_name": project.name,
        "channel": placement.channel,
        "target_url": placement.target_url,
        "archive": {
            "version": f"PR-{placement.id}-v1",
            "archive_note": placement.archive_note or placement.notes,
            "archived_at": (placement.published_at or placement.created_at).isoformat(),
            "visibility": placement.visibility,
            "delivery_status": placement.delivery_status,
        },
        "baseline_time": baseline.isoformat() if baseline else None,
        "metric_deltas": {
            "sample_size_delta": after_sample_size - before_sample_size,
            "company_mention_rate_delta": mention_delta,
            "company_recommendation_rate_delta": recommendation_delta,
            "source_after_appearances": source_after_appearances,
        },
        "evidence": {
            "before_sample_size": before_sample_size,
            "after_sample_size": after_sample_size,
            "review_crawl_task_id": review_crawl_task_id,
            "review_queue_job_id": review_queue_job_id,
            "review_task_status": review_task_status,
            "review_alert_id": review_alert.id if review_alert else None,
        },
        "next_actions": recommendations,
    }

    return PlacementImpactRead(
        placement=placement,
        baseline_time=baseline,
        before=before,
        after=after,
        source_after_appearances=source_after_appearances,
        summary=(
            f"投放基准时间后共采集 {after['total_answers']} 条答案，"
            f"企业提及率变化 {mention_delta:.0%}，推荐率变化 {recommendation_delta:.0%}。"
        ),
        recommendations=recommendations,
        review_report=review_report,
    )


@router.post("/placements/{placement_id}/impact/action-goals", response_model=list[ProjectStageGoalRead])
def create_placement_impact_action_goals(
    project_id: int,
    placement_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CONTENT_ROLES)),
) -> list[ProjectStageGoalRead]:
    project = get_project_or_404(db, project_id)
    placement = get_placement_or_404(db, project_id, placement_id)
    goals = create_placement_impact_goals(db, project, placement)
    for goal in goals:
        record_audit_log(
            db,
            user=user,
            action="placement_impact.action_goal.create",
            resource_type="project_stage_goal",
            resource_id=goal.id,
            project_id=project.id,
            company_id=project.company_id,
            detail={
                "placement_id": placement.id,
                "channel": placement.channel,
                "metric_key": goal.metric_key,
                "title": goal.title,
            },
        )
    db.commit()
    return [
        ProjectStageGoalRead.model_validate(goal).model_copy(
            update={"suggested_actions": goal_suggested_actions(goal, "unknown")}
        )
        for goal in goals
    ]


def _pct(value: float | int | None) -> str:
    return f"{float(value or 0):.0%}"


def _delta_pct(value: float | int | None) -> str:
    normalized = float(value or 0)
    sign = "+" if normalized > 0 else ""
    return f"{sign}{normalized:.0%}"


def _delivery_status_label(value: str | None) -> str:
    labels = {
        "not_delivered": "未交付",
        "ready": "待交付",
        "delivered": "已交付",
        "accepted": "已确认",
    }
    return labels.get(value or "", value or "未交付")


def _access_event_label(value: str) -> str:
    labels = {
        "view_package": "打开交付包",
        "export_markdown": "下载 Markdown",
        "export_pdf": "下载 PDF",
        "confirm_report": "确认阅读",
    }
    return labels.get(value, value)


def _delivery_package_summary(project_id: int, db: Session) -> dict:
    project = get_project_or_404(db, project_id)
    placements = list(
        db.scalars(
            select(PlacementRecord)
            .where(PlacementRecord.project_id == project_id)
            .where(PlacementRecord.status == "published")
            .where(PlacementRecord.visibility == "customer_visible")
            .where(PlacementRecord.delivery_status.in_(DELIVERABLE_STATUSES))
            .order_by(PlacementRecord.published_at.desc(), PlacementRecord.created_at.desc())
        )
    )
    shares = list(
        db.scalars(
            select(DeliveryPackageShare)
            .where(DeliveryPackageShare.project_id == project_id)
            .order_by(DeliveryPackageShare.created_at.desc())
        )
    )
    logs = list(
        db.scalars(
            select(DeliveryPackageAccessLog)
            .where(DeliveryPackageAccessLog.project_id == project_id)
            .order_by(DeliveryPackageAccessLog.created_at.desc())
            .limit(50)
        )
    )
    impacts = [get_placement_impact(project_id, placement.id, db) for placement in placements]
    return {"project": project, "placements": placements, "shares": shares, "logs": logs, "impacts": impacts}


def _render_delivery_package_markdown(project_id: int, db: Session) -> str:
    summary = _delivery_package_summary(project_id, db)
    project = summary["project"]
    placements = summary["placements"]
    shares = summary["shares"]
    logs = summary["logs"]
    impacts = summary["impacts"]
    accepted_count = sum(1 for item in placements if item.delivery_status == "accepted")
    lines = [
        f"# {project.name} 客户交付包汇总",
        "",
        f"- 可交付报告：{len(placements)}",
        f"- 客户已确认：{accepted_count}",
        f"- 分享链接：{len(shares)}",
        f"- 访问记录：{len(logs)}",
        "",
        "## 交付报告",
        "",
    ]
    if not impacts:
        lines.append("- 暂无客户可见交付报告。")
    for impact in impacts:
        report = impact.review_report
        archive = report.get("archive", {})
        deltas = report.get("metric_deltas", {})
        lines.extend(
            [
                f"### {archive.get('version') or f'PR-{impact.placement.id}-v1'}",
                "",
                f"- 渠道：{impact.placement.channel}",
                f"- 状态：{_delivery_status_label(archive.get('delivery_status'))}",
                f"- 结论：{report.get('conclusion')}",
                f"- 备注：{archive.get('archive_note') or impact.placement.archive_note or impact.placement.notes or '暂无'}",
                f"- 样本变化：{deltas.get('sample_size_delta', 0)}",
                f"- 企业提及率变化：{_delta_pct(deltas.get('company_mention_rate_delta'))}",
                f"- 企业推荐率变化：{_delta_pct(deltas.get('company_recommendation_rate_delta'))}",
                "",
            ]
        )
    lines.extend(["## 分享链接", ""])
    if not shares:
        lines.append("- 暂无分享链接。")
    for share in shares:
        lines.append(
            f"- {share.name}｜{share.status}｜/share/delivery/{share.token}｜"
            f"最后访问：{share.last_accessed_at or '未访问'}"
        )
    lines.extend(["", "## 最近访问与确认", ""])
    if not logs:
        lines.append("- 暂无访问记录。")
    for log in logs[:20]:
        target = f"报告 {log.placement_id}" if log.placement_id else "交付包"
        actor = f"｜{log.actor_name}" if log.actor_name else ""
        comment = f"｜{log.comment}" if log.comment else ""
        lines.append(f"- {log.created_at}｜{_access_event_label(log.event_type)}｜{target}{actor}{comment}")
    lines.append("")
    return "\n".join(lines)


def _render_delivery_package_pdf(project_id: int, db: Session) -> bytes:
    from io import BytesIO

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    font_name = "Helvetica"
    for font_path in [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
    ]:
        try:
            pdfmetrics.registerFont(TTFont("GeoCJK", font_path))
            font_name = "GeoCJK"
            break
        except Exception:
            continue

    markdown = _render_delivery_package_markdown(project_id, db)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("GeoPackageTitle", parent=styles["Title"], fontName=font_name, fontSize=20, leading=26)
    heading_style = ParagraphStyle("GeoPackageHeading", parent=styles["Heading2"], fontName=font_name, fontSize=14, leading=18)
    body_style = ParagraphStyle("GeoPackageBody", parent=styles["BodyText"], fontName=font_name, fontSize=10, leading=16)
    story = []
    for line in markdown.splitlines():
        if line.startswith("# "):
            story.append(Paragraph(line.removeprefix("# "), title_style))
        elif line.startswith("## "):
            story.append(Spacer(1, 6))
            story.append(Paragraph(line.removeprefix("## "), heading_style))
        elif line.startswith("### "):
            story.append(Paragraph(line.removeprefix("### "), heading_style))
        elif line:
            story.append(Paragraph(line.replace("｜", " / "), body_style))
        else:
            story.append(Spacer(1, 4))
    doc.build(story)
    return buffer.getvalue()


def _render_placement_review_markdown(impact: PlacementImpactRead) -> str:
    report = impact.review_report
    deltas = report.get("metric_deltas", {})
    evidence = report.get("evidence", {})
    lines = [
        f"# {report.get('project_name')} 投放复盘报告",
        "",
        f"- 投放渠道：{report.get('channel')}",
        f"- 目标 URL：{report.get('target_url') or '未设置'}",
        f"- 报告版本：{(report.get('archive') or {}).get('version') or 'v1'}",
        f"- 归档备注：{(report.get('archive') or {}).get('archive_note') or '暂无'}",
        f"- 可见范围：{(report.get('archive') or {}).get('visibility') or 'internal'}",
        f"- 交付状态：{(report.get('archive') or {}).get('delivery_status') or 'not_delivered'}",
        f"- 复盘基准时间：{report.get('baseline_time')}",
        f"- 复盘状态：{report.get('status')}",
        "",
        "## 复盘结论",
        "",
        str(report.get("conclusion") or ""),
        "",
        "## 核心指标变化",
        "",
        f"- 样本量变化：{deltas.get('sample_size_delta', 0)}",
        f"- 企业提及率变化：{_delta_pct(deltas.get('company_mention_rate_delta'))}",
        f"- 企业推荐率变化：{_delta_pct(deltas.get('company_recommendation_rate_delta'))}",
        f"- 投放信源出现次数：{deltas.get('source_after_appearances', 0)}",
        "",
        "## 投放前后对比",
        "",
        f"- 投放前样本：{impact.before.get('total_answers', 0)}",
        f"- 投放前企业提及率：{_pct(impact.before.get('company_mention_rate'))}",
        f"- 投放前企业推荐率：{_pct(impact.before.get('company_recommendation_rate'))}",
        f"- 投放后样本：{impact.after.get('total_answers', 0)}",
        f"- 投放后企业提及率：{_pct(impact.after.get('company_mention_rate'))}",
        f"- 投放后企业推荐率：{_pct(impact.after.get('company_recommendation_rate'))}",
        "",
        "## 复盘证据",
        "",
        f"- 复盘采集任务：{evidence.get('review_crawl_task_id') or '暂无'}",
        f"- 队列任务：{evidence.get('review_queue_job_id') or '暂无'}",
        f"- 复盘任务状态：{evidence.get('review_task_status') or '暂无'}",
        "",
        "## 下一步动作",
        "",
    ]
    lines.extend(f"- {item}" for item in report.get("next_actions", []))
    lines.append("")
    return "\n".join(lines)


def _render_placement_review_pdf(impact: PlacementImpactRead) -> bytes:
    from io import BytesIO

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    font_name = "Helvetica"
    for font_path in [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
    ]:
        try:
            pdfmetrics.registerFont(TTFont("GeoCJK", font_path))
            font_name = "GeoCJK"
            break
        except Exception:
            continue

    report = impact.review_report
    archive = report.get("archive", {})
    deltas = report.get("metric_deltas", {})
    evidence = report.get("evidence", {})
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("GeoTitle", parent=styles["Title"], fontName=font_name, fontSize=20, leading=26)
    heading_style = ParagraphStyle("GeoHeading", parent=styles["Heading2"], fontName=font_name, fontSize=14, leading=18)
    body_style = ParagraphStyle("GeoBody", parent=styles["BodyText"], fontName=font_name, fontSize=10, leading=16)
    story = [
        Paragraph(f"{report.get('project_name')} 投放复盘报告", title_style),
        Paragraph(
            f"投放渠道：{report.get('channel')}<br/>"
            f"目标 URL：{report.get('target_url') or '未设置'}<br/>"
            f"报告版本：{archive.get('version') or 'v1'}<br/>"
            f"归档备注：{archive.get('archive_note') or '暂无'}<br/>"
            f"可见范围：{archive.get('visibility') or 'internal'}<br/>"
            f"交付状态：{archive.get('delivery_status') or 'not_delivered'}",
            body_style,
        ),
        Spacer(1, 6),
        Paragraph("复盘结论", heading_style),
        Paragraph(str(report.get("conclusion") or ""), body_style),
        Paragraph("核心指标变化", heading_style),
        Paragraph(
            f"样本量变化：{deltas.get('sample_size_delta', 0)}<br/>"
            f"企业提及率变化：{_delta_pct(deltas.get('company_mention_rate_delta'))}<br/>"
            f"企业推荐率变化：{_delta_pct(deltas.get('company_recommendation_rate_delta'))}<br/>"
            f"投放信源出现次数：{deltas.get('source_after_appearances', 0)}",
            body_style,
        ),
        Paragraph("投放前后对比", heading_style),
        Paragraph(
            f"投放前样本：{impact.before.get('total_answers', 0)}<br/>"
            f"投放前企业提及率：{_pct(impact.before.get('company_mention_rate'))}<br/>"
            f"投放前企业推荐率：{_pct(impact.before.get('company_recommendation_rate'))}<br/>"
            f"投放后样本：{impact.after.get('total_answers', 0)}<br/>"
            f"投放后企业提及率：{_pct(impact.after.get('company_mention_rate'))}<br/>"
            f"投放后企业推荐率：{_pct(impact.after.get('company_recommendation_rate'))}",
            body_style,
        ),
        Paragraph("复盘证据", heading_style),
        Paragraph(
            f"复盘采集任务：{evidence.get('review_crawl_task_id') or '暂无'}<br/>"
            f"队列任务：{evidence.get('review_queue_job_id') or '暂无'}<br/>"
            f"复盘任务状态：{evidence.get('review_task_status') or '暂无'}",
            body_style,
        ),
        Paragraph("下一步动作", heading_style),
    ]
    for item in report.get("next_actions", []):
        story.append(Paragraph(f"• {item}", body_style))
    doc.build(story)
    return buffer.getvalue()


@router.get("/placements/{placement_id}/impact/export/markdown", response_class=PlainTextResponse)
def export_placement_impact_markdown(
    project_id: int, placement_id: int, db: Session = Depends(get_db)
) -> str:
    impact = get_placement_impact(project_id, placement_id, db)
    return _render_placement_review_markdown(impact)


@router.get("/placements/{placement_id}/impact/export/pdf")
def export_placement_impact_pdf(
    project_id: int, placement_id: int, db: Session = Depends(get_db)
) -> Response:
    impact = get_placement_impact(project_id, placement_id, db)
    pdf = _render_placement_review_pdf(impact)
    filename = f"geo-placement-impact-{placement_id}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/delivery-package/export/markdown", response_class=PlainTextResponse)
def export_delivery_package_markdown(project_id: int, db: Session = Depends(get_db)) -> str:
    get_project_or_404(db, project_id)
    return _render_delivery_package_markdown(project_id, db)


@router.get("/delivery-package/export/pdf")
def export_delivery_package_pdf(project_id: int, db: Session = Depends(get_db)) -> Response:
    get_project_or_404(db, project_id)
    pdf = _render_delivery_package_pdf(project_id, db)
    filename = f"geo-delivery-package-{project_id}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@public_router.get("/{token}", response_model=PublicDeliveryPackageRead)
def get_public_delivery_package(
    token: str,
    db: Session = Depends(get_db),
    user_agent: str | None = Header(default=None),
) -> PublicDeliveryPackageRead:
    share = _get_share_or_404(db, token)
    _consume_public_delivery_rate(
        db,
        share_id=share.id,
        scope="public-delivery-read",
        limit=get_settings().public_delivery_read_rate_limit_per_hour,
    )
    _record_delivery_access(
        db,
        share,
        "view_package",
        detail={"user_agent": user_agent},
    )
    payload = _public_delivery_package_payload(share, db)
    db.commit()
    return payload


@public_router.get("/{token}/placements/{placement_id}/export/markdown", response_class=PlainTextResponse)
def export_public_delivery_markdown(
    token: str,
    placement_id: int,
    db: Session = Depends(get_db),
    user_agent: str | None = Header(default=None),
) -> str:
    share = _get_share_or_404(db, token)
    _consume_public_delivery_rate(
        db,
        share_id=share.id,
        scope="public-delivery-read",
        limit=get_settings().public_delivery_read_rate_limit_per_hour,
    )
    placement = get_placement_or_404(db, share.project_id, placement_id)
    if not _is_customer_deliverable(placement):
        raise HTTPException(status_code=404, detail="Delivery report not found")
    _record_delivery_access(
        db,
        share,
        "export_markdown",
        placement_id=placement_id,
        detail={"user_agent": user_agent},
    )
    impact = get_placement_impact(share.project_id, placement_id, db)
    db.commit()
    return _render_placement_review_markdown(impact)


@public_router.get("/{token}/placements/{placement_id}/export/pdf")
def export_public_delivery_pdf(
    token: str,
    placement_id: int,
    db: Session = Depends(get_db),
    user_agent: str | None = Header(default=None),
) -> Response:
    share = _get_share_or_404(db, token)
    _consume_public_delivery_rate(
        db,
        share_id=share.id,
        scope="public-delivery-read",
        limit=get_settings().public_delivery_read_rate_limit_per_hour,
    )
    placement = get_placement_or_404(db, share.project_id, placement_id)
    if not _is_customer_deliverable(placement):
        raise HTTPException(status_code=404, detail="Delivery report not found")
    _record_delivery_access(
        db,
        share,
        "export_pdf",
        placement_id=placement_id,
        detail={"user_agent": user_agent},
    )
    impact = get_placement_impact(share.project_id, placement_id, db)
    pdf = _render_placement_review_pdf(impact)
    db.commit()
    filename = f"geo-delivery-report-{placement_id}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@public_router.post("/{token}/placements/{placement_id}/confirm", response_model=DeliveryPackageAccessLogRead)
def confirm_public_delivery_report(
    token: str,
    placement_id: int,
    payload: PublicDeliveryConfirmRequest,
    db: Session = Depends(get_db),
    user_agent: str | None = Header(default=None),
) -> DeliveryPackageAccessLog:
    share = _get_share_or_404(db, token)
    _consume_public_delivery_rate(
        db,
        share_id=share.id,
        scope="public-delivery-confirm",
        limit=get_settings().public_delivery_confirm_rate_limit_per_hour,
    )
    if not share.confirmation_token_encrypted:
        raise HTTPException(status_code=409, detail="该分享尚未生成专用验收码")
    expected_confirmation = decrypt_secret(share.confirmation_token_encrypted)
    if not secrets.compare_digest(payload.confirmation_token, expected_confirmation):
        raise HTTPException(status_code=403, detail="验收码无效")
    placement = get_placement_or_404(db, share.project_id, placement_id)
    if not _is_customer_deliverable(placement):
        raise HTTPException(status_code=404, detail="Delivery report not found")
    existing_confirmation = db.scalar(
        select(DeliveryPackageAccessLog)
        .where(
            DeliveryPackageAccessLog.share_id == share.id,
            DeliveryPackageAccessLog.placement_id == placement_id,
            DeliveryPackageAccessLog.event_type == "confirm_report",
        )
        .order_by(DeliveryPackageAccessLog.created_at.desc())
    )
    if placement.delivery_status == "accepted":
        if existing_confirmation is not None:
            return existing_confirmation
        raise HTTPException(status_code=409, detail="该报告已经验收")
    consumed = db.execute(
        update(PlacementRecord)
        .where(
            PlacementRecord.id == placement.id,
            PlacementRecord.delivery_status.in_(("ready", "delivered")),
        )
        .values(delivery_status="accepted")
    )
    if consumed.rowcount != 1:
        db.rollback()
        existing_confirmation = db.scalar(
            select(DeliveryPackageAccessLog)
            .where(
                DeliveryPackageAccessLog.share_id == share.id,
                DeliveryPackageAccessLog.placement_id == placement_id,
                DeliveryPackageAccessLog.event_type == "confirm_report",
            )
            .order_by(DeliveryPackageAccessLog.created_at.desc())
        )
        if existing_confirmation is not None:
            return existing_confirmation
        raise HTTPException(status_code=409, detail="该报告已经验收")
    access_log = _record_delivery_access(
        db,
        share,
        "confirm_report",
        placement_id=placement_id,
        actor_name=payload.actor_name,
        comment=payload.comment,
        detail={"user_agent": user_agent},
    )
    db.flush()
    project = get_project_or_404(db, share.project_id)
    stage_goal = _stage_goal_for_placement(db, project.id, placement.id)
    if stage_goal is not None:
        stage_goal.status = "completed"
        record_audit_log(
            db,
            user=None,
            action="stage_goal.delivery_confirmed",
            resource_type="delivery_package_access_log",
            resource_id=access_log.id,
            project_id=project.id,
            company_id=project.company_id,
            detail={
                "stage_goal_id": stage_goal.id,
                "placement_id": placement.id,
                "access_log_id": access_log.id,
                "share_id": share.id,
                "actor_name": payload.actor_name,
                "comment": payload.comment,
                "confirmation_method": "separate_confirmation_code",
            },
        )
    alert = SystemAlert(
        company_id=project.company_id,
        project_id=project.id,
        alert_type="delivery.confirmed",
        severity="info",
        status="open",
        title=f"客户已确认交付报告：{placement.channel}",
        message=(
            f"{payload.actor_name or '客户'} 已确认阅读 {placement.channel} 的交付复盘报告。"
            f"{' 备注：' + payload.comment if payload.comment else ''}"
        ),
        detail_json={
            "share_id": share.id,
            "placement_id": placement.id,
            "access_log_id": access_log.id,
            "stage_goal_id": stage_goal.id if stage_goal is not None else None,
            "actor_name": payload.actor_name,
            "comment": payload.comment,
            "confirmation_method": "separate_confirmation_code",
        },
    )
    db.add(alert)
    db.commit()
    db.refresh(access_log)
    return access_log


@router.post("/article-drafts/generate", response_model=ArticleDraftRead, status_code=201)
def generate_project_article_draft(
    project_id: int,
    payload: ArticleDraftGenerate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CONTENT_ROLES)),
) -> ArticleDraft:
    project = get_project_or_404(db, project_id)
    draft = generate_article_draft(db, project, payload)
    record_audit_log(
        db,
        user=user,
        action="article_draft.generate",
        resource_type="article_draft",
        resource_id=draft.id,
        project_id=project.id,
        company_id=project.company_id,
        detail={"draft_type": draft.draft_type, "title": draft.title},
    )
    db.commit()
    return draft


@router.get("/article-drafts", response_model=list[ArticleDraftRead])
def list_article_drafts(project_id: int, db: Session = Depends(get_db)) -> list[ArticleDraft]:
    get_project_or_404(db, project_id)
    return list(
        db.scalars(
            select(ArticleDraft)
            .where(ArticleDraft.project_id == project_id)
            .order_by(ArticleDraft.created_at.desc())
        )
    )


@router.get("/article-drafts/{draft_id}", response_model=ArticleDraftRead)
def get_article_draft(project_id: int, draft_id: int, db: Session = Depends(get_db)) -> ArticleDraft:
    return get_draft_or_404(db, project_id, draft_id)


@router.patch("/article-drafts/{draft_id}", response_model=ArticleDraftRead)
def update_article_draft(
    project_id: int,
    draft_id: int,
    payload: ArticleDraftUpdate,
    db: Session = Depends(get_db),
    _user: object = Depends(require_roles(*CONTENT_ROLES)),
) -> ArticleDraft:
    draft = get_draft_or_404(db, project_id, draft_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(draft, field, value)
    db.commit()
    db.refresh(draft)
    return draft


@router.post("/article-drafts/{draft_id}/reviews", response_model=ArticleReviewRead, status_code=201)
def create_article_review(
    project_id: int,
    draft_id: int,
    payload: ArticleReviewCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*REVIEW_ROLES)),
) -> ArticleReview:
    draft = get_draft_or_404(db, project_id, draft_id)
    review = review_article_draft(db, draft, payload.review_type)
    record_audit_log(
        db,
        user=user,
        action="article_draft.review",
        resource_type="article_review",
        resource_id=review.id,
        project_id=project_id,
        detail={"draft_id": draft.id, "total_score": review.total_score, "grade": review.grade},
    )
    db.commit()
    return review


@router.post(
    "/article-drafts/{draft_id}/human-review",
    response_model=ArticleReviewRead,
    status_code=201,
)
def decide_article_draft_human_review(
    project_id: int,
    draft_id: int,
    payload: HumanReviewDecision,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*REVIEW_ROLES)),
) -> ArticleReview:
    project = get_project_or_404(db, project_id)
    draft = get_draft_or_404(db, project_id, draft_id)
    review = decide_article_draft_review(
        db,
        draft,
        reviewer_id=user.id,
        decision=payload.decision,
        comment=payload.comment,
    )
    record_audit_log(
        db,
        user=user,
        action="article_draft.human_review",
        resource_type="article_review",
        resource_id=review.id,
        project_id=project_id,
        company_id=project.company_id,
        detail={"draft_id": draft.id, "decision": payload.decision, "comment": payload.comment},
    )
    db.commit()
    db.refresh(review)
    return review


@router.post("/article-drafts/{draft_id}/revise", response_model=ArticleDraftRead, status_code=201)
def revise_article_draft(
    project_id: int,
    draft_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CONTENT_ROLES, *REVIEW_ROLES)),
) -> ArticleDraft:
    project = get_project_or_404(db, project_id)
    draft = get_draft_or_404(db, project_id, draft_id)
    revised = revise_article_draft_from_review(db, draft)
    revised_review = review_article_draft(db, revised, review_type="ai")
    latest_review = db.scalar(
        select(ArticleReview)
        .where(ArticleReview.article_draft_id == draft.id)
        .order_by(ArticleReview.created_at.desc(), ArticleReview.id.desc())
        .limit(1)
    )
    record_audit_log(
        db,
        user=user,
        action="article_draft.revise_from_review",
        resource_type="article_draft",
        resource_id=revised.id,
        project_id=project_id,
        company_id=project.company_id,
        detail={
            "source_draft_id": draft.id,
            "source_review_id": latest_review.id if latest_review else None,
            "revised_review_id": revised_review.id,
            "revised_score": revised_review.total_score,
            "revised_grade": revised_review.grade,
        },
    )
    db.commit()
    return revised


@router.get("/article-drafts/{draft_id}/reviews", response_model=list[ArticleReviewRead])
def list_article_reviews(
    project_id: int, draft_id: int, db: Session = Depends(get_db)
) -> list[ArticleReview]:
    get_draft_or_404(db, project_id, draft_id)
    return list(
        db.scalars(
            select(ArticleReview)
            .where(ArticleReview.article_draft_id == draft_id)
            .order_by(ArticleReview.created_at.desc())
        )
    )


@router.post("/article-drafts/{draft_id}/approve", response_model=ArticleDraftRead)
def approve_article_draft(
    project_id: int,
    draft_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*REVIEW_ROLES)),
) -> ArticleDraft:
    draft = get_draft_or_404(db, project_id, draft_id)
    draft.status = "approved"
    record_audit_log(
        db,
        user=user,
        action="article_draft.approve",
        resource_type="article_draft",
        resource_id=draft.id,
        project_id=project_id,
        detail={"title": draft.title},
    )
    db.commit()
    db.refresh(draft)
    return draft


@router.post("/article-drafts/{draft_id}/reject", response_model=ArticleDraftRead)
def reject_article_draft(
    project_id: int,
    draft_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*REVIEW_ROLES)),
) -> ArticleDraft:
    draft = get_draft_or_404(db, project_id, draft_id)
    draft.status = "rejected"
    record_audit_log(
        db,
        user=user,
        action="article_draft.reject",
        resource_type="article_draft",
        resource_id=draft.id,
        project_id=project_id,
        detail={"title": draft.title},
    )
    db.commit()
    db.refresh(draft)
    return draft


@router.delete("/article-drafts/{draft_id}", response_model=APIMessage)
def delete_article_draft(
    project_id: int,
    draft_id: int,
    db: Session = Depends(get_db),
    _user: object = Depends(require_roles(*CONTENT_ROLES)),
) -> APIMessage:
    draft = get_draft_or_404(db, project_id, draft_id)
    linked_placement_count = db.scalar(
        select(func.count(PlacementRecord.id)).where(PlacementRecord.article_draft_id == draft.id)
    )
    if linked_placement_count:
        raise HTTPException(
            status_code=409,
            detail="Article draft is linked to placement records and cannot be deleted",
        )
    for review in db.scalars(select(ArticleReview).where(ArticleReview.article_draft_id == draft.id)):
        db.delete(review)
    db.delete(draft)
    db.commit()
    return APIMessage(message="Article draft deleted")
