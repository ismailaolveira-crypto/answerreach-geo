from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.cleanroom_v1 import (
    GeoActionApproval,
    GeoActionCompletionEvidence,
    GeoActionEvent,
    GeoActionOpportunity,
    GeoActionOpportunityEvidence,
    GeoActionTarget,
    GeoAgentRun,
    GeoContentAsset,
    GeoContentBrief,
    GeoDistributionRun,
    GeoDistributionTarget,
    GeoOptimizationAction,
    GeoPlatformVariant,
    GeoReobservation,
)
from app.models.user import User
from app.models.workspace_access import WorkspaceMembership
from app.services.workspace_access import membership_for, require_workspace_access


ACTION_TYPES = {
    "article",
    "official_site",
    "structured_data",
    "third_party_source",
    "analysis",
    "legacy_unclassified",
}

ACTION_STAGES = {
    "proposed",
    "accepted",
    "in_progress",
    "awaiting_approval",
    "executing",
    "partially_completed",
    "ready_for_retest",
    "completed",
    "blocked",
    "changes_requested",
    "cancelled",
}

MEASUREMENT_STATUSES = {
    "not_eligible",
    "eligible",
    "retesting",
    "partially_measured",
    "measured",
    "inconclusive",
}

TARGET_WORKFLOWS: dict[str, tuple[str, ...]] = {
    "article": (
        "target_selected",
        "variant_generating",
        "awaiting_fact_review",
        "awaiting_platform_review",
        "draft_ready",
        "draft_write_requested",
        "draft_link_returned",
        "draft_saved",
        "awaiting_human_publish",
        "publicly_verified",
    ),
    "official_site": (
        "gap_confirmed",
        "change_proposed",
        "awaiting_brand_legal_review",
        "handed_to_web_owner",
        "deployed",
        "same_domain_readback_verified",
    ),
    "structured_data": (
        "schema_gap_confirmed",
        "jsonld_proposed",
        "awaiting_technical_review",
        "deployed",
        "source_readback_verified",
        "schema_validated",
    ),
    "third_party_source": (
        "source_selected",
        "cooperation_briefed",
        "external_execution",
        "external_content_live",
        "public_readback_verified",
    ),
    "analysis": (
        "scope_confirmed",
        "analysis_in_progress",
        "awaiting_analysis_review",
        "analysis_verified",
    ),
}

TARGET_TYPES_BY_ACTION: dict[str, set[str]] = {
    "article": {"platform"},
    "official_site": {"official_page"},
    "structured_data": {"schema"},
    "third_party_source": {"external_source"},
    "analysis": {"analysis_deliverable"},
}

FINAL_TARGET_STATUS = {
    action_type: workflow[-1] for action_type, workflow in TARGET_WORKFLOWS.items()
}

APPROVAL_STATES = {
    "article": {"awaiting_fact_review", "awaiting_platform_review"},
    "official_site": {"awaiting_brand_legal_review"},
    "structured_data": {"awaiting_technical_review"},
    "third_party_source": set(),
    "analysis": {"awaiting_analysis_review"},
}

TARGET_DEFAULTS: dict[str, tuple[str, str]] = {
    "article": ("platform", "target_selected"),
    "official_site": ("official_page", "gap_confirmed"),
    "structured_data": ("schema", "schema_gap_confirmed"),
    "third_party_source": ("external_source", "source_selected"),
    "analysis": ("analysis_deliverable", "scope_confirmed"),
}

MANAGER_ROLES = {"owner", "admin"}
MUTATING_ROLES = {"owner", "admin", "operator", "reviewer"}

ARTICLE_SYSTEM_MANAGED_STATUSES = set(TARGET_WORKFLOWS["article"])


def utcnow() -> datetime:
    return datetime.now(UTC)


def is_past(value: datetime | None) -> bool:
    if value is None:
        return False
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized < utcnow()


def canonical_fingerprint(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def action_or_404(
    db: Session, workspace_id: int, action_id: int
) -> GeoOptimizationAction:
    action = db.get(GeoOptimizationAction, action_id)
    if action is None or action.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Action not found")
    return action


def target_or_404(db: Session, action: GeoOptimizationAction, target_id: int) -> GeoActionTarget:
    target = db.get(GeoActionTarget, target_id)
    if (
        target is None
        or target.workspace_id != action.workspace_id
        or target.action_id != action.id
    ):
        raise HTTPException(status_code=404, detail="Action target not found")
    return target


def approval_or_404(
    db: Session, action: GeoOptimizationAction, approval_id: int
) -> GeoActionApproval:
    approval = db.get(GeoActionApproval, approval_id)
    if (
        approval is None
        or approval.workspace_id != action.workspace_id
        or approval.action_id != action.id
    ):
        raise HTTPException(status_code=404, detail="Action approval not found")
    return approval


def workspace_role(
    db: Session, user: User, workspace_id: int
) -> WorkspaceMembership | None:
    _workspace, membership = require_workspace_access(db, user, workspace_id)
    if user.role == "super_admin":
        return membership
    if membership is None or membership.role not in MUTATING_ROLES:
        raise HTTPException(status_code=403, detail="Workspace write permission required")
    return membership


def require_manager(
    db: Session, user: User, workspace_id: int
) -> WorkspaceMembership | None:
    membership = workspace_role(db, user, workspace_id)
    if user.role != "super_admin" and (
        membership is None or membership.role not in MANAGER_ROLES
    ):
        raise HTTPException(status_code=403, detail="Workspace admin permission required")
    return membership


def assert_active_member(
    db: Session, workspace_id: int, user_id: int
) -> WorkspaceMembership:
    membership = membership_for(db, workspace_id, user_id)
    if membership is None:
        raise HTTPException(status_code=422, detail="负责人必须是当前工作区的活跃成员")
    return membership


def assert_assignee_or_manager(
    db: Session, user: User, action: GeoOptimizationAction
) -> WorkspaceMembership | None:
    membership = workspace_role(db, user, action.workspace_id)
    if user.role == "super_admin":
        return membership
    if membership and membership.role in MANAGER_ROLES:
        return membership
    if membership and membership.role == "operator" and action.assignee_user_id == user.id:
        return membership
    raise HTTPException(status_code=403, detail="只有负责人或工作区管理员可以执行此操作")


def classify_opportunity(opportunity: GeoActionOpportunity) -> tuple[str, str]:
    asset_type = str(opportunity.recommended_asset_type or "").strip().lower()
    opportunity_type = str(opportunity.opportunity_type or "").strip().lower()
    platforms = {
        str(value).strip().lower()
        for value in (opportunity.recommended_platforms or [])
        if str(value).strip()
    }
    if asset_type in {"structured_data", "schema", "json_ld", "json-ld"}:
        return "structured_data", "json_ld"
    if asset_type in {"third_party_source", "external_source"}:
        return "third_party_source", "external_public_content"
    if (
        opportunity_type in {"website_citation_readiness", "website_scope_gap"}
        or asset_type in {"website", "website_recommendation", "official_site"}
        or platforms == {"official_site"}
    ):
        return "official_site", "official_page_change"
    if asset_type == "article" or any(platform != "official_site" for platform in platforms):
        return "article", "platform_article"
    return "legacy_unclassified", "legacy_deliverable"


def opportunity_scope_fields(
    db: Session, opportunity: GeoActionOpportunity
) -> tuple[list[int], list[str], str]:
    evidence_links = list(
        db.scalars(
            select(GeoActionOpportunityEvidence)
            .where(GeoActionOpportunityEvidence.opportunity_id == opportunity.id)
            .order_by(GeoActionOpportunityEvidence.id.asc())
        )
    )
    question_ids = sorted(
        {
            int(link.question_plan_id)
            for link in evidence_links
            if link.question_plan_id is not None
        }
    )
    scope_question = int((opportunity.scope_snapshot or {}).get("question_plan_id") or 0)
    if scope_question:
        question_ids = sorted({*question_ids, scope_question})
    model_keys = sorted(
        {str(link.model_key).strip() for link in evidence_links if str(link.model_key).strip()}
    )
    scope_models = [
        str(value).strip()
        for value in (opportunity.scope_snapshot or {}).get("model_keys") or []
        if str(value).strip()
    ]
    model_keys = sorted({*model_keys, *scope_models})
    return question_ids, model_keys, canonical_fingerprint(opportunity.scope_snapshot or {})


def create_opportunity_targets(
    db: Session,
    action: GeoOptimizationAction,
    opportunity: GeoActionOpportunity,
) -> list[GeoActionTarget]:
    if action.action_type == "legacy_unclassified":
        return []
    target_type, initial_status = TARGET_DEFAULTS[action.action_type]
    values = [
        str(value).strip().lower()
        for value in (opportunity.recommended_platforms or [])
        if str(value).strip()
    ]
    if action.action_type in {"official_site", "structured_data"}:
        values = ["official_site"]
    rows: list[GeoActionTarget] = []
    for ordinal, value in enumerate(dict.fromkeys(values)):
        display_name = "官网" if value == "official_site" else value
        target = GeoActionTarget(
            workspace_id=action.workspace_id,
            action_id=action.id,
            target_key=f"opportunity:{opportunity.id}:{value}",
            target_type=target_type,
            platform_key=value if target_type == "platform" else None,
            display_name=display_name,
            target_ref=value,
            delivery_status=initial_status,
            ordinal=ordinal,
            metadata_json={
                "source": "opportunity",
                "opportunity_id": opportunity.id,
            },
        )
        db.add(target)
        rows.append(target)
    db.flush()
    return rows


def append_event(
    db: Session,
    *,
    action: GeoOptimizationAction,
    event_type: str,
    actor_user_id: int | None,
    from_stage: str | None = None,
    to_stage: str | None = None,
    detail: dict[str, Any] | None = None,
    actor_type: str = "user",
) -> GeoActionEvent:
    event = GeoActionEvent(
        workspace_id=action.workspace_id,
        action_id=action.id,
        event_type=event_type,
        from_stage=from_stage,
        to_stage=to_stage,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        detail=detail or {},
    )
    db.add(event)
    return event


def action_targets(db: Session, action_id: int) -> list[GeoActionTarget]:
    return list(
        db.scalars(
            select(GeoActionTarget)
            .where(GeoActionTarget.action_id == action_id)
            .order_by(GeoActionTarget.ordinal.asc(), GeoActionTarget.id.asc())
        )
    )


def action_approvals(db: Session, action_id: int) -> list[GeoActionApproval]:
    return list(
        db.scalars(
            select(GeoActionApproval)
            .where(GeoActionApproval.action_id == action_id)
            .order_by(GeoActionApproval.id.desc())
        )
    )


def action_evidence(db: Session, action_id: int) -> list[GeoActionCompletionEvidence]:
    return list(
        db.scalars(
            select(GeoActionCompletionEvidence)
            .where(GeoActionCompletionEvidence.action_id == action_id)
            .order_by(GeoActionCompletionEvidence.id.desc())
        )
    )


def target_is_final(action_type: str, delivery_status: str) -> bool:
    return FINAL_TARGET_STATUS.get(action_type) == delivery_status


def _article_target_truth(
    db: Session,
    action: GeoOptimizationAction,
    target: GeoActionTarget,
) -> tuple[str, str, str | None, int | None]:
    """Derive an article target status from durable business evidence.

    ``GeoActionTarget.delivery_status`` is a denormalized projection.  Content,
    draft and publication tables are authoritative because they carry the
    review, readback and public-page evidence.  Returning the source alongside
    the status keeps the API explainable and prevents UI labels from guessing.
    """

    distribution_rows = db.execute(
        select(GeoDistributionTarget, GeoDistributionRun)
        .join(
            GeoDistributionRun,
            GeoDistributionRun.id == GeoDistributionTarget.distribution_run_id,
        )
        .where(
            GeoDistributionRun.action_id == action.id,
            GeoDistributionTarget.platform_key == target.platform_key,
        )
        .order_by(GeoDistributionRun.id.desc(), GeoDistributionTarget.id.desc())
    ).all()
    for distribution_target, _distribution_run in distribution_rows:
        distribution_target_id = int(distribution_target.id)
        if (
            distribution_target.human_publish_status == "published"
            and distribution_target.public_url
            and distribution_target.publication_verification_status == "publicly_verified"
        ):
            return (
                "publicly_verified",
                "distribution_publication",
                "人工发布结果和公开页面均已核验。",
                distribution_target_id,
            )
    for distribution_target, _distribution_run in distribution_rows:
        distribution_target_id = int(distribution_target.id)
        if (
            distribution_target.draft_readback_status == "draft_saved"
            and distribution_target.draft_url
        ):
            return (
                "awaiting_human_publish",
                "draft_readback",
                "草稿已由用户确认可见，等待在目标平台人工发布。",
                distribution_target_id,
            )
    for distribution_target, _distribution_run in distribution_rows:
        distribution_target_id = int(distribution_target.id)
        if (
            distribution_target.request_status == "draft_link_returned"
            and distribution_target.draft_readback_status == "awaiting_human_confirmation"
            and distribution_target.candidate_draft_url
        ):
            return (
                "draft_link_returned",
                "candidate_draft",
                "助手已返回候选草稿地址，仍需用户打开并确认正文可见。",
                distribution_target_id,
            )
    if distribution_rows:
        distribution_target, distribution_run = distribution_rows[0]
        distribution_target_id = int(distribution_target.id)
        if distribution_target.request_status in {
            "mcp_request_accepted",
            "request_accepted",
            "pending",
        } or (
            distribution_run.assistant_task_issued_at is not None
            and distribution_run.status in {"pending", "partial"}
        ):
            return (
                "draft_write_requested",
                "distribution_request",
                "草稿写入任务已发出，正在等待逐平台结果。",
                distribution_target_id,
            )
    if distribution_rows:
        distribution_target, _distribution_run = distribution_rows[0]
        distribution_target_id = int(distribution_target.id)
        if distribution_target.request_status == "failed":
            return (
                "draft_ready",
                "distribution_failure",
                "平台稿已审核，但上次草稿写入失败，可以单独重试。",
                distribution_target_id,
            )
        if distribution_target.request_status == "cancelled":
            return (
                "draft_ready",
                "distribution_cancelled",
                "平台稿已审核，上次草稿写入已取消。",
                distribution_target_id,
            )
        return (
            "draft_ready",
            "distribution_target",
            "平台稿已审核，可以交给 GEO 文章助手写入草稿。",
            distribution_target_id,
        )

    variant_row = db.execute(
        select(GeoPlatformVariant, GeoContentAsset)
        .join(GeoContentAsset, GeoContentAsset.id == GeoPlatformVariant.content_asset_id)
        .join(GeoContentBrief, GeoContentBrief.id == GeoContentAsset.brief_id)
        .where(
            GeoContentBrief.action_id == action.id,
            GeoPlatformVariant.platform_key == target.platform_key,
        )
        .order_by(
            GeoContentAsset.version.desc(),
            GeoContentAsset.id.desc(),
            GeoPlatformVariant.version.desc(),
            GeoPlatformVariant.id.desc(),
        )
    ).first()
    if variant_row is not None:
        variant, _asset = variant_row
        if variant.status == "approved":
            return "draft_ready", "approved_variant", "平台稿已审核，可以写入草稿。", None
        if variant.status == "changes_requested":
            return "variant_generating", "variant_changes_requested", "平台稿已退回，等待修订。", None
        return "awaiting_platform_review", "platform_variant", "平台稿已经生成，等待人工审核。", None

    asset = db.scalar(
        select(GeoContentAsset)
        .join(GeoContentBrief, GeoContentBrief.id == GeoContentAsset.brief_id)
        .where(GeoContentBrief.action_id == action.id)
        .order_by(GeoContentAsset.version.desc(), GeoContentAsset.id.desc())
    )
    if asset is not None:
        if asset.status == "changes_requested":
            return "variant_generating", "content_changes_requested", "内容已退回，等待修订。", None
        return "variant_generating", "content_asset", "母稿已经生成，正在准备对应平台稿。", None

    active_agent_run = db.scalar(
        select(GeoAgentRun.id)
        .where(
            GeoAgentRun.action_id == action.id,
            GeoAgentRun.status.in_(["queued", "running", "waiting_human"]),
        )
        .order_by(GeoAgentRun.id.desc())
    )
    if active_agent_run is not None:
        return "variant_generating", "agent_run", "内容生成任务正在执行。", None
    return "target_selected", "action_target", "尚未为该平台生成内容。", None


def effective_target_truth(
    db: Session,
    action: GeoOptimizationAction,
    target: GeoActionTarget,
) -> tuple[str, str, str | None, int | None]:
    if action.action_type == "article" and target.target_type == "platform":
        return _article_target_truth(db, action, target)
    return target.delivery_status, "action_target", None, None


def synchronize_article_action_targets(
    db: Session,
    action: GeoOptimizationAction | None,
) -> list[dict[str, Any]]:
    """Refresh the denormalized article-target cache before a business commit."""

    if action is None or action.action_type != "article":
        return []
    changes: list[dict[str, Any]] = []
    for target in action_targets(db, action.id):
        status, source, note, distribution_target_id = effective_target_truth(
            db, action, target
        )
        if status == target.delivery_status:
            continue
        previous = target.delivery_status
        target.delivery_status = status
        if status == "publicly_verified":
            evidence = db.scalar(
                select(GeoActionCompletionEvidence)
                .where(
                    GeoActionCompletionEvidence.action_id == action.id,
                    GeoActionCompletionEvidence.target_id == target.id,
                    GeoActionCompletionEvidence.verification_status == "verified",
                )
                .order_by(GeoActionCompletionEvidence.id.desc())
            )
            target.verified_at = evidence.verified_at if evidence else target.verified_at
            target.completed_at = target.verified_at or utcnow()
        changes.append(
            {
                "target_id": target.id,
                "from_status": previous,
                "to_status": status,
                "status_source": source,
                "status_note": note,
                "distribution_target_id": distribution_target_id,
            }
        )
    if changes:
        refresh_action_delivery_stage(db, action)
    return changes


def _has_comparable_retest(db: Session, action: GeoOptimizationAction) -> bool:
    return (
        db.scalar(
            select(GeoReobservation.id)
            .where(
                GeoReobservation.action_id == action.id,
                GeoReobservation.status == "completed",
                GeoReobservation.conclusion.in_(("improved", "unchanged", "regressed")),
            )
            .limit(1)
        )
        is not None
    )


def mark_matching_distribution_published(
    db: Session,
    action: GeoOptimizationAction,
    target: GeoActionTarget,
    *,
    public_url: str,
    user_id: int,
) -> GeoDistributionTarget | None:
    """Keep command-center evidence and workbench publication receipts aligned."""

    row = db.execute(
        select(GeoDistributionTarget, GeoDistributionRun)
        .join(
            GeoDistributionRun,
            GeoDistributionRun.id == GeoDistributionTarget.distribution_run_id,
        )
        .where(
            GeoDistributionRun.action_id == action.id,
            GeoDistributionTarget.platform_key == target.platform_key,
            GeoDistributionTarget.draft_readback_status == "draft_saved",
        )
        .order_by(GeoDistributionRun.id.desc(), GeoDistributionTarget.id.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    distribution_target, distribution_run = row
    now = utcnow()
    distribution_target.human_publish_status = "published"
    distribution_target.public_url = public_url
    distribution_target.publication_verification_status = "publicly_verified"
    distribution_target.published_at = now
    distribution_target.published_by_user_id = user_id
    distribution_target.final_action_clicked = False
    db.add(distribution_target)
    siblings = list(
        db.scalars(
            select(GeoDistributionTarget).where(
                GeoDistributionTarget.distribution_run_id == distribution_run.id
            )
        )
    )
    all_published = bool(siblings) and all(
        item.human_publish_status == "published"
        and item.public_url
        and item.publication_verification_status == "publicly_verified"
        for item in siblings
    )
    distribution_run.stage = "published" if all_published else "awaiting_publication"
    distribution_run.status = "published" if all_published else "partial"
    db.add(distribution_run)
    return distribution_target


def derive_delivery_stage(
    db: Session,
    action: GeoOptimizationAction,
    target_statuses: dict[int, str] | None = None,
) -> str:
    targets = action_targets(db, action.id)
    if not targets:
        return action.stage
    final_count = sum(
        1
        for target in targets
        if target_is_final(
            action.action_type,
            (target_statuses or {}).get(target.id, target.delivery_status),
        )
    )
    if final_count == len(targets):
        if _has_comparable_retest(db, action):
            return "completed"
        return "ready_for_retest"
    if final_count:
        return "partially_completed"
    if any(
        (target_statuses or {}).get(target.id, target.delivery_status)
        in APPROVAL_STATES.get(action.action_type, set())
        for target in targets
    ):
        return "awaiting_approval"
    workflow = TARGET_WORKFLOWS.get(action.action_type, ())
    if workflow and any(
        (target_statuses or {}).get(target.id, target.delivery_status) != workflow[0]
        for target in targets
    ):
        return "executing"
    return "in_progress" if action.stage not in {"proposed", "accepted"} else action.stage


def refresh_action_delivery_stage(db: Session, action: GeoOptimizationAction) -> None:
    if action.stage in {"blocked", "cancelled", "changes_requested"}:
        return
    stage = derive_delivery_stage(db, action)
    action.stage = stage
    if stage == "completed":
        action.status = "in_progress"
        action.completed_at = utcnow()
    elif stage == "ready_for_retest":
        action.status = "in_progress"
        action.completed_at = None
    elif stage not in {"proposed"}:
        action.status = "in_progress"


def validate_target_transition(
    action: GeoOptimizationAction,
    target: GeoActionTarget,
    to_status: str,
) -> None:
    workflow = TARGET_WORKFLOWS.get(action.action_type)
    if workflow is None:
        raise HTTPException(status_code=409, detail="旧行动需要先由管理员确认行动类型")
    if target.target_type not in TARGET_TYPES_BY_ACTION[action.action_type]:
        raise HTTPException(status_code=409, detail="目标类型与行动流程不一致")
    if target.delivery_status == to_status:
        return
    if target.delivery_status not in workflow or to_status not in workflow:
        raise HTTPException(status_code=409, detail="目标状态不属于当前行动流程")
    current_index = workflow.index(target.delivery_status)
    if current_index + 1 >= len(workflow) or workflow[current_index + 1] != to_status:
        raise HTTPException(status_code=409, detail="不能跳过当前行动流程的必要步骤")


def next_target_status(action: GeoOptimizationAction, target: GeoActionTarget) -> str | None:
    workflow = TARGET_WORKFLOWS.get(action.action_type, ())
    if target.delivery_status not in workflow:
        return None
    index = workflow.index(target.delivery_status)
    return workflow[index + 1] if index + 1 < len(workflow) else None


def action_payload(db: Session, action: GeoOptimizationAction) -> dict[str, Any]:
    targets = action_targets(db, action.id)
    approvals = action_approvals(db, action.id)
    evidence = action_evidence(db, action.id)
    target_truth = {
        target.id: effective_target_truth(db, action, target) for target in targets
    }
    target_statuses = {
        target_id: truth[0] for target_id, truth in target_truth.items()
    }
    target_payloads = []
    for target in targets:
        effective_status, status_source, status_note, distribution_target_id = target_truth[
            target.id
        ]
        target_payloads.append(
            {
                "id": target.id,
                "workspace_id": target.workspace_id,
                "action_id": target.action_id,
                "target_key": target.target_key,
                "target_type": target.target_type,
                "platform_key": target.platform_key,
                "display_name": target.display_name,
                "target_ref": target.target_ref,
                "delivery_status": effective_status,
                "recorded_delivery_status": target.delivery_status,
                "status_source": status_source,
                "status_note": status_note,
                "distribution_target_id": distribution_target_id,
                "ordinal": target.ordinal,
                "metadata_json": target.metadata_json or {},
                "completed_at": target.completed_at,
                "completed_by_user_id": target.completed_by_user_id,
                "verified_at": target.verified_at,
                "created_at": target.created_at,
                "updated_at": target.updated_at,
            }
        )
    verified_target_ids = {
        row.target_id for row in evidence if row.verification_status == "verified"
    }
    final_target_ids = {
        target.id
        for target in targets
        if target_is_final(action.action_type, target_statuses[target.id])
    }
    eligible_target_ids = sorted(final_target_ids & verified_target_ids)
    effective_stage = (
        action.stage
        if action.stage in {"blocked", "cancelled", "changes_requested"}
        else derive_delivery_stage(db, action, target_statuses)
    )
    return {
        "id": action.id,
        "workspace_id": action.workspace_id,
        "question_plan_id": action.question_plan_id,
        "source_evidence_id": action.source_evidence_id,
        "opportunity_id": action.opportunity_id,
        "title": action.title,
        "rationale": action.rationale,
        "hypothesis": action.hypothesis,
        "priority": action.priority,
        "status": action.status,
        "stage": effective_stage,
        "baseline_snapshot": action.baseline_snapshot or {},
        "selected_scope": action.selected_scope or {},
        "measurement_plan": action.measurement_plan or {},
        "blocked_reason": action.blocked_reason,
        "selected_at": action.selected_at,
        "completed_at": action.completed_at,
        "action_type": action.action_type,
        "deliverable_type": action.deliverable_type,
        "workflow_version": action.workflow_version,
        "assignee_user_id": action.assignee_user_id,
        "due_at": action.due_at,
        "approval_due_at": action.approval_due_at,
        "approval_requested_at": action.approval_requested_at,
        "blocked_reason_code": action.blocked_reason_code,
        "blocked_note": action.blocked_note,
        "affected_question_ids": action.affected_question_ids or [],
        "affected_model_keys": action.affected_model_keys or [],
        "scope_fingerprint": action.scope_fingerprint,
        "measurement_status": action.measurement_status,
        "completed_target_count": len(final_target_ids),
        "retest_eligible_target_count": len(eligible_target_ids),
        "eligible_target_ids": eligible_target_ids,
        "is_overdue": bool(is_past(action.due_at) and effective_stage != "completed"),
        "next_action": next_action_label(
            db,
            action,
            targets,
            approvals,
            target_statuses=target_statuses,
        ),
        "targets": target_payloads,
        "approvals": approvals,
        "evidence": evidence,
    }


def next_action_label(
    db: Session,
    action: GeoOptimizationAction,
    targets: list[GeoActionTarget] | None = None,
    approvals: list[GeoActionApproval] | None = None,
    target_statuses: dict[int, str] | None = None,
) -> str:
    targets = targets if targets is not None else action_targets(db, action.id)
    approvals = approvals if approvals is not None else action_approvals(db, action.id)
    if action.action_type == "legacy_unclassified":
        return "确认行动类型"
    if action.stage == "proposed":
        return "分配负责人并接受"
    if action.stage == "blocked":
        return "处理阻塞"
    pending = next((row for row in approvals if row.status == "pending"), None)
    if pending:
        return "等待审批"
    for target in targets:
        effective_status = (target_statuses or {}).get(target.id, target.delivery_status)
        workflow = TARGET_WORKFLOWS.get(action.action_type, ())
        next_status = None
        if effective_status in workflow:
            index = workflow.index(effective_status)
            next_status = workflow[index + 1] if index + 1 < len(workflow) else None
        if next_status:
            return next_status
    if action.measurement_status == "eligible":
        return "创建局部复测"
    return "查看结果"


def next_approval_version(
    db: Session, action_id: int, target_id: int | None, approval_type: str
) -> int:
    return int(
        db.scalar(
            select(func.max(GeoActionApproval.version)).where(
                GeoActionApproval.action_id == action_id,
                GeoActionApproval.target_id == target_id,
                GeoActionApproval.approval_type == approval_type,
            )
        )
        or 0
    ) + 1
