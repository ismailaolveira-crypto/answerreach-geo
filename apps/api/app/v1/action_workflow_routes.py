from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.cleanroom_v1 import (
    GeoActionApproval,
    GeoActionCompletionEvidence,
    GeoActionEvent,
    GeoActionTarget,
    GeoOptimizationAction,
)
from app.models.user import User
from app.services.workspace_access import membership_for, require_workspace_access
from app.v1.action_workflow import (
    ARTICLE_SYSTEM_MANAGED_STATUSES,
    FINAL_TARGET_STATUS,
    MANAGER_ROLES,
    TARGET_DEFAULTS,
    TARGET_TYPES_BY_ACTION,
    action_or_404,
    action_payload,
    action_targets,
    append_event,
    approval_or_404,
    assert_active_member,
    assert_assignee_or_manager,
    canonical_fingerprint,
    effective_target_truth,
    next_target_status,
    next_approval_version,
    refresh_action_delivery_stage,
    require_manager,
    target_is_final,
    target_or_404,
    utcnow,
    validate_target_transition,
    workspace_role,
)
from app.v1.action_workflow_schemas import (
    ActionAcceptRequest,
    ActionApprovalCreate,
    ActionApprovalDecision,
    ActionApprovalRead,
    ActionAssignRequest,
    ActionBlockRequest,
    ActionClassifyRequest,
    ActionDetailRead,
    ActionEvidenceCreate,
    ActionEvidenceRead,
    ActionRescheduleRequest,
    ActionTargetCreate,
    ActionTargetRead,
    ActionUnblockRequest,
    TargetTransitionRequest,
)
from app.v1.website_audit import (
    PublicationVerificationError,
    WebsiteAuditTargetError,
    verify_publication_page,
    verify_structured_data_page,
)


router = APIRouter(prefix="/v1", tags=["action-execution-v2"])

PLATFORM_DOMAINS = {
    "zhihu": ("zhihu.com",),
    "juejin": ("juejin.cn",),
    "csdn": ("csdn.net",),
    "51cto": ("51cto.com",),
    "wechat": ("mp.weixin.qq.com",),
    "xiaohongshu": ("xiaohongshu.com",),
}

REQUIRED_APPROVAL_BY_STATUS = {
    "awaiting_fact_review": "fact",
    "awaiting_platform_review": "platform_draft",
    "awaiting_brand_legal_review": "brand_legal",
    "awaiting_technical_review": "technical",
    "awaiting_analysis_review": "analysis",
}

REQUIRED_EVIDENCE_BY_ACTION = {
    "article": {"public_url"},
    "official_site": {"same_domain_readback"},
    "structured_data": {"source_code", "schema_validation"},
    "third_party_source": {"external_publication"},
    "analysis": {"analysis_report"},
}


def _future_datetime(value: datetime, label: str) -> datetime:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if normalized <= utcnow():
        raise HTTPException(status_code=422, detail=f"{label}必须晚于当前时间")
    return normalized


def _active_role(db: Session, workspace_id: int, user_id: int) -> str | None:
    membership = membership_for(db, workspace_id, user_id)
    return membership.role if membership else None


def _approval_cache(db: Session, action: GeoOptimizationAction) -> None:
    pending = list(
        db.scalars(
            select(GeoActionApproval)
            .where(
                GeoActionApproval.action_id == action.id,
                GeoActionApproval.status == "pending",
            )
            .order_by(GeoActionApproval.due_at.asc(), GeoActionApproval.id.asc())
        )
    )
    action.approval_due_at = pending[0].due_at if pending else None
    action.approval_requested_at = pending[0].requested_at if pending else None


def _latest_approved(
    db: Session,
    *,
    action_id: int,
    target_id: int,
    approval_type: str,
) -> GeoActionApproval | None:
    return db.scalar(
        select(GeoActionApproval)
        .where(
            GeoActionApproval.action_id == action_id,
            or_(
                GeoActionApproval.target_id == target_id,
                GeoActionApproval.target_id.is_(None),
            ),
            GeoActionApproval.approval_type == approval_type,
            GeoActionApproval.status == "approved",
        )
        .order_by(GeoActionApproval.version.desc(), GeoActionApproval.id.desc())
    )


def _verified_evidence_types(
    db: Session, action_id: int, target_id: int
) -> set[str]:
    return {
        str(value)
        for value in db.scalars(
            select(GeoActionCompletionEvidence.evidence_type).where(
                GeoActionCompletionEvidence.action_id == action_id,
                GeoActionCompletionEvidence.target_id == target_id,
                GeoActionCompletionEvidence.verification_status == "verified",
            )
        )
    }


def _assert_final_evidence(
    db: Session, action: GeoOptimizationAction, target: GeoActionTarget, to_status: str
) -> None:
    if FINAL_TARGET_STATUS.get(action.action_type) != to_status:
        return
    required = REQUIRED_EVIDENCE_BY_ACTION[action.action_type]
    available = _verified_evidence_types(db, action.id, target.id)
    missing = sorted(required - available)
    if missing:
        raise HTTPException(
            status_code=409,
            detail="完成目标前必须先通过真实证据校验：" + "、".join(missing),
        )


def _assert_host_matches_target(
    *,
    workspace_website_url: str | None,
    target: GeoActionTarget,
    verified_url: str,
) -> None:
    host = (urlsplit(verified_url).hostname or "").lower().rstrip(".")
    if target.target_type in {"official_page", "schema"}:
        expected_host = (urlsplit(workspace_website_url or "").hostname or "").lower().rstrip(".")
        if not expected_host:
            raise HTTPException(status_code=422, detail="请先配置工作区官网域名")
        if host != expected_host and not host.endswith(f".{expected_host}"):
            raise HTTPException(status_code=422, detail="证据地址必须属于当前工作区官网")
        return
    if target.target_type == "external_source":
        target_ref = str(target.target_ref or "").strip()
        expected_host = (urlsplit(target_ref).hostname or "").lower().rstrip(".")
        platform_key = str(target.platform_key or target_ref).strip().lower()
        allowed_domains = (expected_host,) if expected_host else PLATFORM_DOMAINS.get(platform_key, ())
        if not allowed_domains:
            raise HTTPException(status_code=422, detail="请先为第三方信源明确可核验的目标域名")
        if not any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains):
            raise HTTPException(status_code=422, detail="证据地址与选定的第三方信源不一致")
        return
    if target.target_type == "platform" and target.platform_key in PLATFORM_DOMAINS:
        domains = PLATFORM_DOMAINS[target.platform_key]
        if not any(host == domain or host.endswith(f".{domain}") for domain in domains):
            raise HTTPException(status_code=422, detail="证据地址与目标平台不一致")


def _verify_evidence(
    *,
    workspace_website_url: str | None,
    target: GeoActionTarget,
    payload: ActionEvidenceCreate,
) -> tuple[str, dict]:
    if payload.evidence_type == "analysis_report":
        summary = str(payload.detail.get("summary") or "").strip()
        if len(summary) < 20:
            raise HTTPException(status_code=422, detail="请填写至少 20 个字的分析结论")
        return "verified", {
            **payload.detail,
            "verification": {"method": "human_analysis_record.v1", "sha256": payload.sha256},
        }
    if not payload.source_url:
        return "pending", {
            **payload.detail,
            "verification_reason": "artifact_requires_separate_readback",
        }
    try:
        if payload.evidence_type == "schema_validation":
            expected_types = [
                str(value)
                for value in payload.detail.get("expected_types") or []
                if str(value).strip()
            ]
            verification = verify_structured_data_page(
                payload.source_url,
                expected_types=expected_types,
            )
        else:
            verification = verify_publication_page(payload.source_url)
        _assert_host_matches_target(
            workspace_website_url=workspace_website_url,
            target=target,
            verified_url=str(verification.get("verified_url") or payload.source_url),
        )
    except (WebsiteAuditTargetError, PublicationVerificationError, HTTPException) as exc:
        reason = exc.detail if isinstance(exc, HTTPException) else str(exc)
        return "rejected", {
            **payload.detail,
            "verification_reason": reason,
            "verifier": "server_public_readback.v1",
        }
    observed_sha = str(verification.get("sha256") or "")
    if payload.sha256 and observed_sha != payload.sha256:
        return "rejected", {
            **payload.detail,
            "verification_reason": "evidence_sha256_mismatch",
            "submitted_sha256": payload.sha256,
            "observed_sha256": observed_sha,
            "verifier": "server_public_readback.v1",
        }
    return "verified", {
        **payload.detail,
        "verification": verification,
        "verifier": "server_public_readback.v1",
    }


@router.get(
    "/workspaces/{workspace_id}/actions/{action_id}",
    response_model=ActionDetailRead,
)
def read_action_detail(
    workspace_id: int,
    action_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_workspace_access(db, user, workspace_id)
    return action_payload(db, action_or_404(db, workspace_id, action_id))


@router.post(
    "/workspaces/{workspace_id}/actions/{action_id}/classify",
    response_model=ActionDetailRead,
)
def classify_action(
    workspace_id: int,
    action_id: int,
    payload: ActionClassifyRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_manager(db, user, workspace_id)
    action = action_or_404(db, workspace_id, action_id)
    if action.action_type != "legacy_unclassified":
        raise HTTPException(status_code=409, detail="行动类型已经确认，不能原地覆盖")
    existing_targets = action_targets(db, action.id)
    if existing_targets:
        raise HTTPException(status_code=409, detail="该旧行动已有目标，请先人工拆分后再确认类型")
    allowed_types = TARGET_TYPES_BY_ACTION[payload.action_type]
    if any(target.target_type not in allowed_types for target in payload.targets):
        raise HTTPException(status_code=422, detail="目标类型与行动类型不一致")
    previous = action.stage
    action.action_type = payload.action_type
    action.deliverable_type = payload.deliverable_type
    action.workflow_version = "action-flow.v2"
    initial_status = TARGET_DEFAULTS[payload.action_type][1]
    for ordinal, item in enumerate(payload.targets):
        db.add(
            GeoActionTarget(
                workspace_id=workspace_id,
                action_id=action.id,
                target_key=item.target_key,
                target_type=item.target_type,
                platform_key=item.platform_key,
                display_name=item.display_name,
                target_ref=item.target_ref,
                delivery_status=initial_status,
                ordinal=ordinal,
                metadata_json={"source": "manual_classification"},
            )
        )
    append_event(
        db,
        action=action,
        event_type="action_classified",
        actor_user_id=user.id,
        from_stage=previous,
        to_stage=action.stage,
        detail={
            "action_type": action.action_type,
            "deliverable_type": action.deliverable_type,
            "target_count": len(payload.targets),
        },
    )
    db.commit()
    db.refresh(action)
    return action_payload(db, action)


@router.post(
    "/workspaces/{workspace_id}/actions/{action_id}/accept",
    response_model=ActionDetailRead,
)
def accept_action(
    workspace_id: int,
    action_id: int,
    payload: ActionAcceptRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    membership = workspace_role(db, user, workspace_id)
    action = action_or_404(db, workspace_id, action_id)
    assignee_membership = assert_active_member(db, workspace_id, payload.assignee_user_id)
    if assignee_membership.role == "viewer":
        raise HTTPException(status_code=422, detail="只读成员不能负责优化行动")
    is_manager = user.role == "super_admin" or bool(
        membership and membership.role in MANAGER_ROLES
    )
    if not is_manager and not (
        membership
        and membership.role == "operator"
        and payload.assignee_user_id == user.id
        and action.assignee_user_id in {None, user.id}
    ):
        raise HTTPException(status_code=403, detail="只有管理员或行动本人可以接受行动")
    if action.action_type == "legacy_unclassified":
        raise HTTPException(status_code=409, detail="请先确认旧行动类型")
    targets = action_targets(db, action.id)
    missing = []
    if not targets:
        missing.append("行动目标")
    if not action.affected_question_ids:
        missing.append("受影响问题")
    if not action.affected_model_keys:
        missing.append("受影响模型")
    if not action.scope_fingerprint:
        missing.append("冻结范围")
    if missing:
        raise HTTPException(status_code=409, detail="接受行动前还缺少：" + "、".join(missing))
    previous = action.stage
    action.assignee_user_id = payload.assignee_user_id
    action.due_at = _future_datetime(payload.due_at, "行动截止时间")
    action.stage = "accepted"
    action.status = "in_progress"
    append_event(
        db,
        action=action,
        event_type="action_accepted",
        actor_user_id=user.id,
        from_stage=previous,
        to_stage="accepted",
        detail={"assignee_user_id": action.assignee_user_id, "due_at": action.due_at.isoformat()},
    )
    db.commit()
    db.refresh(action)
    return action_payload(db, action)


@router.post(
    "/workspaces/{workspace_id}/actions/{action_id}/assign",
    response_model=ActionDetailRead,
)
def assign_action(
    workspace_id: int,
    action_id: int,
    payload: ActionAssignRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_manager(db, user, workspace_id)
    action = action_or_404(db, workspace_id, action_id)
    membership = assert_active_member(db, workspace_id, payload.assignee_user_id)
    if membership.role == "viewer":
        raise HTTPException(status_code=422, detail="只读成员不能负责优化行动")
    previous_assignee = action.assignee_user_id
    action.assignee_user_id = payload.assignee_user_id
    append_event(
        db,
        action=action,
        event_type="action_assigned",
        actor_user_id=user.id,
        from_stage=action.stage,
        to_stage=action.stage,
        detail={
            "previous_assignee_user_id": previous_assignee,
            "assignee_user_id": action.assignee_user_id,
            "reason": payload.reason,
        },
    )
    db.commit()
    db.refresh(action)
    return action_payload(db, action)


@router.post(
    "/workspaces/{workspace_id}/actions/{action_id}/reschedule",
    response_model=ActionDetailRead,
)
def reschedule_action(
    workspace_id: int,
    action_id: int,
    payload: ActionRescheduleRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_manager(db, user, workspace_id)
    action = action_or_404(db, workspace_id, action_id)
    previous_due_at = action.due_at
    action.due_at = _future_datetime(payload.due_at, "新的截止时间")
    append_event(
        db,
        action=action,
        event_type="action_rescheduled",
        actor_user_id=user.id,
        from_stage=action.stage,
        to_stage=action.stage,
        detail={
            "previous_due_at": previous_due_at.isoformat() if previous_due_at else None,
            "due_at": action.due_at.isoformat(),
            "reason": payload.reason,
        },
    )
    db.commit()
    db.refresh(action)
    return action_payload(db, action)


@router.post(
    "/workspaces/{workspace_id}/actions/{action_id}/block",
    response_model=ActionDetailRead,
)
def block_action(
    workspace_id: int,
    action_id: int,
    payload: ActionBlockRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    action = action_or_404(db, workspace_id, action_id)
    assert_assignee_or_manager(db, user, action)
    if action.stage == "blocked":
        if action.blocked_reason_code == payload.reason_code and action.blocked_note == payload.note:
            return action_payload(db, action)
        raise HTTPException(status_code=409, detail="行动已经处于阻塞状态")
    previous = action.stage
    action.stage = "blocked"
    action.status = "in_progress"
    action.blocked_reason_code = payload.reason_code
    action.blocked_note = payload.note
    action.blocked_reason = payload.note
    append_event(
        db,
        action=action,
        event_type="action_blocked",
        actor_user_id=user.id,
        from_stage=previous,
        to_stage="blocked",
        detail={
            "reason_code": payload.reason_code,
            "note": payload.note,
            "resume_stage": previous,
        },
    )
    db.commit()
    db.refresh(action)
    return action_payload(db, action)


@router.post(
    "/workspaces/{workspace_id}/actions/{action_id}/unblock",
    response_model=ActionDetailRead,
)
def unblock_action(
    workspace_id: int,
    action_id: int,
    payload: ActionUnblockRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    action = action_or_404(db, workspace_id, action_id)
    assert_assignee_or_manager(db, user, action)
    if action.stage != "blocked":
        raise HTTPException(status_code=409, detail="行动当前并未阻塞")
    block_event = db.scalar(
        select(GeoActionEvent)
        .where(
            GeoActionEvent.action_id == action.id,
            GeoActionEvent.event_type == "action_blocked",
        )
        .order_by(GeoActionEvent.id.desc())
    )
    resume_stage = str((block_event.detail or {}).get("resume_stage") or "in_progress")
    if resume_stage in {"blocked", "cancelled", "completed"}:
        resume_stage = "in_progress"
    action.stage = resume_stage
    action.blocked_reason_code = None
    action.blocked_note = None
    action.blocked_reason = None
    append_event(
        db,
        action=action,
        event_type="action_unblocked",
        actor_user_id=user.id,
        from_stage="blocked",
        to_stage=resume_stage,
        detail={"note": payload.note},
    )
    db.commit()
    db.refresh(action)
    return action_payload(db, action)


@router.post(
    "/workspaces/{workspace_id}/actions/{action_id}/targets",
    response_model=ActionTargetRead,
    status_code=201,
)
def add_action_target(
    workspace_id: int,
    action_id: int,
    payload: ActionTargetCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    action = action_or_404(db, workspace_id, action_id)
    assert_assignee_or_manager(db, user, action)
    if action.action_type == "legacy_unclassified":
        raise HTTPException(status_code=409, detail="请先确认行动类型")
    if payload.target_type not in TARGET_TYPES_BY_ACTION[action.action_type]:
        raise HTTPException(status_code=422, detail="目标类型与行动流程不一致")
    if db.scalar(
        select(GeoActionTarget).where(
            GeoActionTarget.action_id == action.id,
            GeoActionTarget.target_key == payload.target_key,
        )
    ):
        raise HTTPException(status_code=409, detail="行动目标键已存在")
    target = GeoActionTarget(
        workspace_id=workspace_id,
        action_id=action.id,
        target_key=payload.target_key,
        target_type=payload.target_type,
        platform_key=payload.platform_key,
        display_name=payload.display_name,
        target_ref=payload.target_ref,
        delivery_status=TARGET_DEFAULTS[action.action_type][1],
        ordinal=len(action_targets(db, action.id)),
        metadata_json={"source": "user"},
    )
    db.add(target)
    db.flush()
    append_event(
        db,
        action=action,
        event_type="action_target_added",
        actor_user_id=user.id,
        from_stage=action.stage,
        to_stage=action.stage,
        detail={"target_id": target.id, "target_key": target.target_key},
    )
    db.commit()
    db.refresh(target)
    return target


@router.post(
    "/workspaces/{workspace_id}/actions/{action_id}/targets/{target_id}/transition",
    response_model=ActionDetailRead,
)
def transition_action_target(
    workspace_id: int,
    action_id: int,
    target_id: int,
    payload: TargetTransitionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    action = action_or_404(db, workspace_id, action_id)
    assert_assignee_or_manager(db, user, action)
    target = target_or_404(db, action, target_id)
    if action.action_type == "article" and payload.to_status in ARTICLE_SYSTEM_MANAGED_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                "文章行动状态由内容审核、GEO 文章助手回读和公开页核验自动推进，"
                "不能手动跳级"
            ),
        )
    duplicate_event = next(
        (
            event
            for event in db.scalars(
                select(GeoActionEvent)
                .where(
                    GeoActionEvent.action_id == action.id,
                    GeoActionEvent.event_type == "action_target_transitioned",
                )
                .order_by(GeoActionEvent.id.desc())
                .limit(100)
            )
            if (event.detail or {}).get("idempotency_key") == payload.idempotency_key
        ),
        None,
    )
    if duplicate_event:
        return action_payload(db, action)
    validate_target_transition(action, target, payload.to_status)
    required_approval = REQUIRED_APPROVAL_BY_STATUS.get(target.delivery_status)
    if required_approval and not _latest_approved(
        db,
        action_id=action.id,
        target_id=target.id,
        approval_type=required_approval,
    ):
        raise HTTPException(status_code=409, detail="当前步骤必须先获得对应审批")
    _assert_final_evidence(db, action, target, payload.to_status)
    previous_target_status = target.delivery_status
    previous_action_stage = action.stage
    target.delivery_status = payload.to_status
    if target_is_final(action.action_type, payload.to_status):
        target.completed_at = utcnow()
        target.completed_by_user_id = user.id
        target.verified_at = target.completed_at
        action.measurement_status = "eligible"
    refresh_action_delivery_stage(db, action)
    append_event(
        db,
        action=action,
        event_type="action_target_transitioned",
        actor_user_id=user.id,
        from_stage=previous_action_stage,
        to_stage=action.stage,
        detail={
            "target_id": target.id,
            "from_status": previous_target_status,
            "to_status": target.delivery_status,
            "note": payload.note,
            "idempotency_key": payload.idempotency_key,
        },
    )
    db.commit()
    db.refresh(action)
    return action_payload(db, action)


@router.post(
    "/workspaces/{workspace_id}/actions/{action_id}/targets/{target_id}/evidence",
    response_model=ActionEvidenceRead,
    status_code=201,
)
def submit_action_evidence(
    workspace_id: int,
    action_id: int,
    target_id: int,
    payload: ActionEvidenceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace, _membership = require_workspace_access(db, user, workspace_id)
    action = action_or_404(db, workspace_id, action_id)
    assert_assignee_or_manager(db, user, action)
    target = target_or_404(db, action, target_id)
    if action.action_type == "article":
        effective_status, _source, _note, _distribution_target_id = effective_target_truth(
            db, action, target
        )
        if effective_status != "awaiting_human_publish":
            raise HTTPException(
                status_code=409,
                detail="只有已确认可见的真实平台草稿才能记录人工发布结果",
            )
    allowed_evidence_types = REQUIRED_EVIDENCE_BY_ACTION.get(action.action_type, set())
    if payload.evidence_type not in allowed_evidence_types:
        raise HTTPException(status_code=422, detail="证据类型与行动类型不一致")
    existing = db.scalar(
        select(GeoActionCompletionEvidence).where(
            GeoActionCompletionEvidence.workspace_id == workspace_id,
            GeoActionCompletionEvidence.idempotency_key == payload.idempotency_key,
        )
    )
    if existing:
        if existing.action_id != action.id or existing.target_id != target.id:
            raise HTTPException(status_code=409, detail="幂等键已被其他证据使用")
        return existing
    superseded = None
    if payload.supersedes_evidence_id:
        superseded = db.get(GeoActionCompletionEvidence, payload.supersedes_evidence_id)
        if (
            superseded is None
            or superseded.action_id != action.id
            or superseded.target_id != target.id
        ):
            raise HTTPException(status_code=404, detail="被更正的证据不存在")
    verification_status, detail = _verify_evidence(
        workspace_website_url=workspace.website_url,
        target=target,
        payload=payload,
    )
    observed_sha = str((detail.get("verification") or {}).get("sha256") or "")
    sha256 = observed_sha or payload.sha256
    if not sha256 and verification_status == "rejected":
        sha256 = canonical_fingerprint(
            {
                "evidence_type": payload.evidence_type,
                "source_url": payload.source_url,
                "verification": detail,
            }
        )
    if not sha256:
        raise HTTPException(status_code=422, detail="缺少可锁定的证据哈希")
    evidence = GeoActionCompletionEvidence(
        workspace_id=workspace_id,
        action_id=action.id,
        target_id=target.id,
        evidence_type=payload.evidence_type,
        source_url=payload.source_url,
        artifact_uri=payload.artifact_uri,
        sha256=sha256,
        verification_status=verification_status,
        detail=detail,
        submitted_by_user_id=user.id,
        verified_by_user_id=None,
        submitted_at=utcnow(),
        verified_at=utcnow() if verification_status == "verified" else None,
        supersedes_evidence_id=superseded.id if superseded else None,
        idempotency_key=payload.idempotency_key,
    )
    db.add(evidence)
    db.flush()
    if superseded:
        superseded.verification_status = "superseded"
    if verification_status == "verified":
        if action.action_type == "analysis" and not _latest_approved(
            db,
            action_id=action.id,
            target_id=target.id,
            approval_type="analysis",
        ):
            raise HTTPException(status_code=409, detail="分析结论审核通过后才能记录完成证据")
        target.verified_at = evidence.verified_at
        required = REQUIRED_EVIDENCE_BY_ACTION[action.action_type]
        if required.issubset(_verified_evidence_types(db, action.id, target.id)):
            previous_target_status = target.delivery_status
            previous_action_stage = action.stage
            target.delivery_status = FINAL_TARGET_STATUS[action.action_type]
            target.completed_at = evidence.verified_at
            target.completed_by_user_id = user.id
            action.measurement_status = "eligible"
            refresh_action_delivery_stage(db, action)
            append_event(
                db,
                action=action,
                event_type="action_target_completed_from_verified_evidence",
                actor_user_id=user.id,
                from_stage=previous_action_stage,
                to_stage=action.stage,
                detail={
                    "target_id": target.id,
                    "from_status": previous_target_status,
                    "to_status": target.delivery_status,
                    "evidence_id": evidence.id,
                    "evidence_type": evidence.evidence_type,
                },
            )
    append_event(
        db,
        action=action,
        event_type="action_evidence_submitted",
        actor_user_id=user.id,
        from_stage=action.stage,
        to_stage=action.stage,
        detail={
            "target_id": target.id,
            "evidence_id": evidence.id,
            "evidence_type": evidence.evidence_type,
            "verification_status": evidence.verification_status,
            "sha256": evidence.sha256,
        },
    )
    db.commit()
    db.refresh(evidence)
    return evidence


@router.post(
    "/workspaces/{workspace_id}/actions/{action_id}/approvals",
    response_model=ActionApprovalRead,
    status_code=201,
)
def request_action_approval(
    workspace_id: int,
    action_id: int,
    payload: ActionApprovalCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    action = action_or_404(db, workspace_id, action_id)
    assert_assignee_or_manager(db, user, action)
    if action.action_type == "article":
        raise HTTPException(
            status_code=409,
            detail="文章事实与平台稿审批必须在真实内容审核页完成",
        )
    if payload.target_id:
        target = target_or_404(db, action, payload.target_id)
        required_approval = REQUIRED_APPROVAL_BY_STATUS.get(target.delivery_status)
        if required_approval != payload.approval_type:
            raise HTTPException(status_code=409, detail="审批类型与目标当前步骤不一致")
    reviewer_membership = assert_active_member(db, workspace_id, payload.reviewer_user_id)
    if reviewer_membership.role not in {"reviewer", "owner", "admin"}:
        raise HTTPException(status_code=422, detail="审批人必须拥有审核或管理权限")
    due_at = _future_datetime(payload.due_at, "审批截止时间")
    version = next_approval_version(
        db, action.id, payload.target_id, payload.approval_type
    )
    approval = GeoActionApproval(
        workspace_id=workspace_id,
        action_id=action.id,
        target_id=payload.target_id,
        approval_type=payload.approval_type,
        status="pending",
        version=version,
        requested_by_user_id=user.id,
        reviewer_user_id=payload.reviewer_user_id,
        due_at=due_at,
        requested_at=utcnow(),
        note=payload.note,
        subject_fingerprint=payload.subject_fingerprint,
    )
    db.add(approval)
    db.flush()
    previous = action.stage
    action.stage = "awaiting_approval"
    _approval_cache(db, action)
    append_event(
        db,
        action=action,
        event_type="action_approval_requested",
        actor_user_id=user.id,
        from_stage=previous,
        to_stage="awaiting_approval",
        detail={
            "approval_id": approval.id,
            "target_id": approval.target_id,
            "approval_type": approval.approval_type,
            "reviewer_user_id": approval.reviewer_user_id,
            "due_at": approval.due_at.isoformat(),
            "subject_fingerprint": approval.subject_fingerprint,
        },
    )
    db.commit()
    db.refresh(approval)
    return approval


@router.post(
    "/workspaces/{workspace_id}/actions/{action_id}/targets/{target_id}/self-approve",
    response_model=ActionDetailRead,
)
def self_approve_action_target(
    workspace_id: int,
    action_id: int,
    target_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Approve the current review phase as the signed-in executor.

    Article fact and platform reviews are one visible confirmation for a solo
    operator, but remain two immutable approval records for later audit and
    team-mode compatibility.
    """
    action = action_or_404(db, workspace_id, action_id)
    assert_assignee_or_manager(db, user, action)
    target = target_or_404(db, action, target_id)
    if action.action_type == "article":
        raise HTTPException(
            status_code=409,
            detail="文章审核必须对应实际内容版本和平台稿，请在内容审核页处理",
        )
    if target.delivery_status not in REQUIRED_APPROVAL_BY_STATUS:
        raise HTTPException(status_code=409, detail="当前步骤无需确认")

    while target.delivery_status in REQUIRED_APPROVAL_BY_STATUS:
        approval_type = REQUIRED_APPROVAL_BY_STATUS[target.delivery_status]
        from_status = target.delivery_status
        to_status = next_target_status(action, target)
        if to_status is None:
            raise HTTPException(status_code=409, detail="当前审批步骤缺少后续状态")
        now = utcnow()
        approval = GeoActionApproval(
            workspace_id=workspace_id,
            action_id=action.id,
            target_id=target.id,
            approval_type=approval_type,
            status="approved",
            version=next_approval_version(db, action.id, target.id, approval_type),
            requested_by_user_id=user.id,
            reviewer_user_id=user.id,
            due_at=now,
            requested_at=now,
            decided_at=now,
            note="当前账号自审确认",
            subject_fingerprint=canonical_fingerprint(
                {
                    "action_id": action.id,
                    "target_id": target.id,
                    "approval_type": approval_type,
                    "delivery_status": from_status,
                    "target_updated_at": target.updated_at.isoformat()
                    if target.updated_at
                    else None,
                }
            ),
        )
        db.add(approval)
        db.flush()
        target.delivery_status = to_status
        append_event(
            db,
            action=action,
            event_type="action_self_approved",
            actor_user_id=user.id,
            from_stage=from_status,
            to_stage=to_status,
            detail={
                "approval_id": approval.id,
                "target_id": target.id,
                "approval_type": approval_type,
                "review_mode": "self",
            },
        )
    refresh_action_delivery_stage(db, action)
    _approval_cache(db, action)
    db.commit()
    db.refresh(action)
    return action_payload(db, action)


@router.post(
    "/workspaces/{workspace_id}/actions/{action_id}/approvals/{approval_id}/decide",
    response_model=ActionDetailRead,
)
def decide_action_approval(
    workspace_id: int,
    action_id: int,
    approval_id: int,
    payload: ActionApprovalDecision,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    membership = workspace_role(db, user, workspace_id)
    action = action_or_404(db, workspace_id, action_id)
    approval = approval_or_404(db, action, approval_id)
    is_manager = user.role == "super_admin" or bool(
        membership and membership.role in MANAGER_ROLES
    )
    if not is_manager and approval.reviewer_user_id != user.id:
        raise HTTPException(status_code=403, detail="只有指定审批人可以处理此审批")
    if approval.status != "pending":
        if approval.status == payload.decision:
            return action_payload(db, action)
        raise HTTPException(status_code=409, detail="审批已经结束，不能覆盖历史决定")
    approval.status = payload.decision
    approval.decided_at = utcnow()
    approval.note = payload.note or approval.note
    previous = action.stage
    if payload.decision == "changes_requested":
        action.stage = "changes_requested"
    else:
        action.stage = "in_progress"
        refresh_action_delivery_stage(db, action)
    _approval_cache(db, action)
    append_event(
        db,
        action=action,
        event_type="action_approval_decided",
        actor_user_id=user.id,
        from_stage=previous,
        to_stage=action.stage,
        detail={
            "approval_id": approval.id,
            "decision": approval.status,
            "note": payload.note,
        },
    )
    db.commit()
    db.refresh(action)
    return action_payload(db, action)


@router.get(
    "/workspaces/{workspace_id}/actions-v2",
    response_model=list[ActionDetailRead],
)
def list_action_execution(
    workspace_id: int,
    view: str = Query(default="all", pattern="^(all|mine|approvals|overdue_blocked)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_workspace_access(db, user, workspace_id)
    query = select(GeoOptimizationAction).where(
        GeoOptimizationAction.workspace_id == workspace_id
    )
    if view == "mine":
        query = query.where(GeoOptimizationAction.assignee_user_id == user.id)
    elif view == "approvals":
        action_ids = select(GeoActionApproval.action_id).where(
            GeoActionApproval.workspace_id == workspace_id,
            GeoActionApproval.reviewer_user_id == user.id,
            GeoActionApproval.status == "pending",
        )
        query = query.where(GeoOptimizationAction.id.in_(action_ids))
    elif view == "overdue_blocked":
        now = utcnow()
        query = query.where(
            or_(
                GeoOptimizationAction.stage == "blocked",
                GeoOptimizationAction.due_at < now,
                GeoOptimizationAction.approval_due_at < now,
            )
        )
    rows = list(db.scalars(query.order_by(GeoOptimizationAction.id.desc())))
    return [action_payload(db, row) for row in rows]
