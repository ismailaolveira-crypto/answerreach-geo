from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import WRITE_ROLES, get_current_user, require_roles
from app.db.session import get_db
from app.models.cleanroom_v1 import GeoQuestionPlan, GeoQuestionReview
from app.models.user import User
from app.v1.observation_service import question_sampling_eligible
from app.v1.route_support import scoped_or_404, workspace_or_404
from app.v1.schemas import (
    QuestionLibraryRead,
    QuestionPlanAction,
    QuestionPlanCreate,
    QuestionPlanMerge,
    QuestionPlanRead,
    QuestionPlanUpdate,
    QuestionReviewRead,
)


router = APIRouter(prefix="/v1", tags=["geo-question-governance-v1"])

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


@router.get("/workspaces/{workspace_id}/question-library", response_model=QuestionLibraryRead)
def read_question_library(
    workspace_id: int,
    search: str | None = Query(default=None, max_length=200),
    status: str | None = Query(default=None, max_length=32),
    stage: str | None = Query(default=None, max_length=40),
    role: str | None = Query(default=None, max_length=60),
    topic: str | None = Query(default=None, max_length=80),
    question_plan_ids: list[int] | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace = workspace_or_404(db, user, workspace_id)
    query = select(GeoQuestionPlan).where(GeoQuestionPlan.workspace_id == workspace_id)
    selected_question_ids = sorted(set(value for value in (question_plan_ids or []) if value > 0))
    if selected_question_ids:
        query = query.where(GeoQuestionPlan.id.in_(selected_question_ids))
    if status and status in QUESTION_STATUSES:
        query = query.where(GeoQuestionPlan.status == status)
    if stage and stage in QUESTION_STAGES:
        query = query.where(GeoQuestionPlan.journey_stage == stage)
    if role and role in QUESTION_ROLES:
        query = query.where(GeoQuestionPlan.role == role)
    if search:
        query = query.where(GeoQuestionPlan.question_text.ilike(f"%{search.strip()}%"))
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
    counts["sampling_eligible"] = sum(question_sampling_eligible(item) for item in all_questions)
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
    for key, value in payload.model_dump(exclude_unset=True).items():
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


def _change_status(
    db: Session,
    *,
    plan: GeoQuestionPlan,
    user: User,
    status: str,
    action: str,
    note: str | None,
) -> GeoQuestionPlan:
    from_status = plan.status
    plan.status = status
    plan.active = status in {"approved", "active"}
    _record_question_review(db, plan, user, action, from_status, note)
    db.commit()
    db.refresh(plan)
    return plan


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
    if plan.status not in {"draft", "pending_review", "rejected"}:
        raise HTTPException(status_code=409, detail="只有待审核问题可以批准")
    plan.approved_by = user.id
    plan.approved_at = datetime.now(timezone.utc)
    plan.rejected_reason = None
    return _change_status(
        db, plan=plan, user=user, status="approved", action="approved", note=payload.note
    )


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
    if plan.status not in {"draft", "pending_review"}:
        raise HTTPException(status_code=409, detail="只有待审核问题可以拒绝")
    plan.rejected_reason = payload.note or "人工拒绝"
    return _change_status(
        db, plan=plan, user=user, status="rejected", action="rejected", note=payload.note
    )


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
    if plan.status not in {"approved", "active"}:
        raise HTTPException(status_code=409, detail="只有已批准问题可以停用")
    return _change_status(
        db, plan=plan, user=user, status="deprecated", action="deprecated", note=payload.note
    )


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
    plan.similar_question_id = target.id
    plan.rejected_reason = f"已合并至问题 #{target.id}"
    return _change_status(
        db, plan=plan, user=user, status="deprecated", action="merged", note=payload.note
    )
