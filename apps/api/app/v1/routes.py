from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import WRITE_ROLES, get_current_user, require_roles
from app.db.session import get_db
from app.models import QueueJob
from app.models.cleanroom_v1 import (
    GeoActionCompletionEvidence,
    GeoActionEvent,
    GeoActionOpportunity,
    GeoActionOpportunityEvidence,
    GeoActionTarget,
    GeoAgentRun,
    GeoBrandFact,
    GeoContentAudit,
    GeoContentAsset,
    GeoDistributionRun,
    GeoDistributionTarget,
    GeoEvidence,
    GeoObservationBatch,
    GeoObservationRun,
    GeoObservationTask,
    GeoOptimizationAction,
    GeoQuestionPlan,
    GeoReobservation,
    GeoReobservationTarget,
    GeoWorkspace,
    GeoWebsiteAudit,
)
from app.models.user import User
from app.v1.schemas import (
    ActionCreate,
    ActionEventRead,
    ActionOpportunityDiscoverRequest,
    ActionOpportunityRead,
    ActionOpportunityScopeRead,
    OpportunityAnalysisRunRead,
    ActionRead,
    ActionStageUpdate,
    ActionUpdate,
    BrandFactCreate,
    BrandFactRead,
    BrandFactSourceCandidatesRead,
    BrandFactUpdate,
    ContentAuditCreate,
    ContentAuditRead,
    MAX_OFFICIAL_OBSERVATION_QUESTIONS,
    OfficialApiObservationBatchCreate,
    ReobservationCreate,
    ActionRetestRead,
    ActionWorkbenchStateRead,
    WebsiteAuditOverviewRead,
    WebsiteAuditRead,
    WebsiteGapAnalysisRequest,
    WebsiteGapAnalysisRunRead,
)
from app.services.audit import record_audit_log
from app.v1.scoring import audit_content_snapshot
from app.v1.observation_routes import (
    _official_api_batch_summary,
    create_provider_web_search_batch,
)
from app.v1.route_support import scoped_or_404, workspace_or_404
from app.v1.content_delivery_routes import (
    _content_review_package,
    _distribution_read,
)
from app.v1.agent_run_routes import (
    _assert_agent_capacity,
    _diagnose_runtime_for_request,
    _resolve_agent_execution,
)
from app.v1.action_opportunities import WEBSITE_RULE_VERSION, valid_action_evidence
from app.v1.agent_errors import public_agent_error
from app.v1.opportunity_agent import (
    AGENT_RULE_VERSION,
    build_opportunity_context,
)
from app.v1.website_gap_agent import (
    WEBSITE_GAP_JOB_TYPE,
    WEBSITE_GAP_RULE_VERSION,
    build_website_gap_context,
    load_skill_contract,
)
from app.v1.action_retests import build_batch_metrics, compare_batches
from app.v1.action_workflow import (
    action_approvals as v2_action_approvals,
    action_payload as v2_action_payload,
    classify_opportunity as classify_action_opportunity,
    create_opportunity_targets,
    is_past as v2_is_past,
    opportunity_scope_fields,
    target_is_final as v2_target_is_final,
)
from app.v1.action_workflow_schemas import ActionRetestCreate
from app.v1.results_roi import default_measurement_plan, derive_action_outcome
from app.v1.brand_facts import (
    BRAND_FACT_CANDIDATES_DISCOVERED_ACTION,
    BRAND_FACT_VERIFICATION_ACTION,
    BRAND_FACT_VERIFICATION_FAILED_ACTION,
    brand_fact_read,
    statement_fingerprint,
)
from app.v1.website_audit import (
    BrandFactSourceVerificationError,
    WebsiteAuditTargetError,
    audit_website,
    discover_brand_fact_source_candidates,
    verify_brand_fact_source,
)


router = APIRouter(prefix="/v1", tags=["clean-room-geo-v1"])

API_ROOT = Path(__file__).resolve().parents[2]
AGENT_ARTIFACT_ROOT = API_ROOT / "private_artifacts" / "agent-runs"


def _opportunity_read(db: Session, opportunity: GeoActionOpportunity) -> dict:
    evidence = list(
        db.scalars(
            select(GeoActionOpportunityEvidence)
            .where(GeoActionOpportunityEvidence.opportunity_id == opportunity.id)
            .order_by(GeoActionOpportunityEvidence.id.asc())
        )
    )
    return {"id": opportunity.id, "evidence": evidence, **opportunity.__dict__}


def _opportunity_analysis_read(job: QueueJob) -> dict:
    payload = dict(job.payload_json or {})
    status = {
        "pending": "queued",
        "running": "running",
        "success": "succeeded",
        "failed": "failed",
    }.get(job.status, "failed")
    stage = str(payload.get("stage") or ("failed" if status == "failed" else "queued"))
    if stage not in {"queued", "preparing", "analyzing", "complete", "failed"}:
        stage = "failed" if status == "failed" else "queued"
    if status == "failed":
        stage = "failed"
    return {
        "job_id": job.id,
        "workspace_id": int(payload.get("workspace_id") or 0),
        "batch_id": int(payload.get("batch_id") or 0),
        "model_keys": list(payload.get("model_keys") or []),
        "question_plan_ids": list(payload.get("question_plan_ids") or []),
        "status": status,
        "stage": stage,
        "evidence_count": int(payload.get("evidence_count") or 0),
        "result_count": int(payload.get("result_count") or 0),
        "no_action_count": int(payload.get("no_action_count") or 0),
        "input_fingerprint": str(payload.get("input_fingerprint") or ""),
        "runtime_key": str(payload.get("runtime_key") or "local_codex"),
        "model": payload.get("model"),
        "reasoning_effort": payload.get("reasoning_effort"),
        "codex_thread_id": payload.get("codex_thread_id"),
        "codex_turn_id": payload.get("codex_turn_id"),
        "analysis_summary": payload.get("analysis_summary"),
        "error_message": public_agent_error(job.error_message),
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


def _website_gap_analysis_read(job: QueueJob) -> dict:
    payload = dict(job.payload_json or {})
    status = {
        "pending": "queued",
        "running": "running",
        "success": "succeeded",
        "failed": "failed",
    }.get(job.status, "failed")
    stage = str(payload.get("stage") or ("failed" if status == "failed" else "queued"))
    if stage not in {"queued", "analyzing", "complete", "failed"}:
        stage = "failed" if status == "failed" else "queued"
    if status == "failed":
        stage = "failed"
    return {
        "job_id": job.id,
        "workspace_id": int(payload.get("workspace_id") or 0),
        "batch_id": int(payload.get("batch_id") or 0),
        "model_keys": list(payload.get("model_keys") or []),
        "question_plan_ids": list(payload.get("question_plan_ids") or []),
        "status": status,
        "stage": stage,
        "evidence_count": int(payload.get("evidence_count") or 0),
        "result_count": int(payload.get("result_count") or 0),
        "recommendation_count": int(payload.get("recommendation_count") or 0),
        "recommendations": list(payload.get("recommendations") or []),
        "input_fingerprint": str(payload.get("input_fingerprint") or ""),
        "runtime_key": str(payload.get("runtime_key") or "local_codex"),
        "model": payload.get("model"),
        "reasoning_effort": payload.get("reasoning_effort"),
        "skill_name": str(payload.get("skill_name") or ""),
        "skill_sha256": str(payload.get("skill_sha256") or ""),
        "official_metrics": dict(payload.get("official_metrics") or {}),
        "codex_thread_id": payload.get("codex_thread_id"),
        "codex_turn_id": payload.get("codex_turn_id"),
        "analysis_summary": payload.get("analysis_summary"),
        "error_message": public_agent_error(job.error_message),
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


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
    response_model=OpportunityAnalysisRunRead,
    status_code=202,
)
def discover_action_opportunities(
    workspace_id: int,
    payload: ActionOpportunityDiscoverRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
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
    if not effective_batch_id:
        raise HTTPException(status_code=422, detail="请先选择一个已完成的真实观测批次")
    try:
        context = build_opportunity_context(
            db,
            workspace_id,
            batch_id=int(effective_batch_id),
            question_plan_ids=payload.question_plan_ids,
            model_keys=selected_model_keys,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    diagnostic = _diagnose_runtime_for_request(payload.runtime_key, invalidate=True)
    if not diagnostic.get("ready"):
        raise HTTPException(
            status_code=409,
            detail=diagnostic.get("error") or "Selected Agent is not ready",
        )
    agent_model, reasoning_effort = _resolve_agent_execution(
        diagnostic,
        requested_model=payload.model or payload.codex_model,
        requested_reasoning_effort=payload.reasoning_effort,
    )

    active_jobs = [
        job
        for job in db.scalars(
            select(QueueJob)
            .where(
                QueueJob.job_type == "geo_opportunity.discover",
                QueueJob.status.in_(("pending", "running")),
            )
            .order_by(QueueJob.id.desc())
        )
        if int((job.payload_json or {}).get("workspace_id") or 0) == workspace_id
    ]
    same_scope = next(
        (
            job
            for job in active_jobs
            if (job.payload_json or {}).get("input_fingerprint")
            == context["input_fingerprint"]
            and (job.payload_json or {}).get("runtime_key", "local_codex") == payload.runtime_key
            and (job.payload_json or {}).get("model") == agent_model
            and (job.payload_json or {}).get("reasoning_effort") == reasoning_effort
        ),
        None,
    )
    if same_scope is not None:
        return _opportunity_analysis_read(same_scope)

    _assert_agent_capacity(db, workspace_id)
    job = QueueJob(
        job_type="geo_opportunity.discover",
        status="pending",
        priority=25,
        scheduled_at=datetime.now(timezone.utc),
        max_attempts=1,
        payload_json={
            "project_id": 0,
            "workspace_id": workspace_id,
            "batch_id": int(effective_batch_id),
            "model_keys": selected_model_keys,
            "question_plan_ids": payload.question_plan_ids,
            "max_items": payload.max_items,
            "input_fingerprint": context["input_fingerprint"],
            "evidence_count": len(context["evidence"]),
            "runtime_key": payload.runtime_key,
            "model": agent_model,
            "reasoning_effort": reasoning_effort,
            "actor_user_id": user.id,
            "stage": "queued",
        },
    )
    db.add(job)
    db.flush()
    db.add(
        GeoActionEvent(
            workspace_id=workspace_id,
            job_id=job.id,
            event_type="opportunity_analysis_queued",
            actor_type="user",
            actor_user_id=user.id,
            detail={
                "batch_id": effective_batch_id,
                "model_keys": selected_model_keys,
                "question_plan_ids": payload.question_plan_ids,
                "input_fingerprint": context["input_fingerprint"],
                "evidence_count": len(context["evidence"]),
                "runtime_key": payload.runtime_key,
                "model": agent_model,
                "reasoning_effort": reasoning_effort,
                "evidence_gate": (
                    "completed_task+real_answer+search_event+source_url+raw_artifact"
                ),
            },
        )
    )
    db.commit()
    db.refresh(job)
    return _opportunity_analysis_read(job)


@router.get(
    "/workspaces/{workspace_id}/action-opportunities/analysis-runs/latest",
    response_model=OpportunityAnalysisRunRead | None,
)
def get_latest_opportunity_analysis(
    workspace_id: int,
    batch_id: int = Query(ge=1),
    model_key: str | None = Query(default=None, min_length=1, max_length=120),
    question_plan_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    expected_models = [model_key] if model_key else []
    expected_questions = [question_plan_id] if question_plan_id else []
    jobs = list(
        db.scalars(
            select(QueueJob)
            .where(QueueJob.job_type == "geo_opportunity.discover")
            .order_by(QueueJob.id.desc())
            .limit(200)
        )
    )
    job = next(
        (
            row
            for row in jobs
            if int((row.payload_json or {}).get("workspace_id") or 0) == workspace_id
            and int((row.payload_json or {}).get("batch_id") or 0) == batch_id
            and list((row.payload_json or {}).get("model_keys") or []) == expected_models
            and list((row.payload_json or {}).get("question_plan_ids") or [])
            == expected_questions
        ),
        None,
    )
    return _opportunity_analysis_read(job) if job else None


@router.get(
    "/workspaces/{workspace_id}/action-opportunities/analysis-runs/{job_id}",
    response_model=OpportunityAnalysisRunRead,
)
def get_opportunity_analysis(
    workspace_id: int,
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    job = db.get(QueueJob, job_id)
    if (
        job is None
        or job.job_type != "geo_opportunity.discover"
        or int((job.payload_json or {}).get("workspace_id") or 0) != workspace_id
    ):
        raise HTTPException(status_code=404, detail="Opportunity analysis run not found")
    return _opportunity_analysis_read(job)


@router.post(
    "/workspaces/{workspace_id}/website-gap-analyses",
    response_model=WebsiteGapAnalysisRunRead,
    status_code=202,
)
def create_website_gap_analysis(
    workspace_id: int,
    payload: WebsiteGapAnalysisRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    scoped_or_404(db, GeoObservationBatch, workspace_id, payload.batch_id)
    selected_models = sorted({value.strip() for value in payload.model_keys if value.strip()})
    selected_questions = sorted({int(value) for value in payload.question_plan_ids})
    for question_id in selected_questions:
        scoped_or_404(db, GeoQuestionPlan, workspace_id, question_id)
    try:
        skill = load_skill_contract()
        context = build_website_gap_context(
            db,
            workspace_id,
            batch_id=payload.batch_id,
            model_keys=selected_models,
            question_plan_ids=selected_questions,
            skill_contract=skill,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


    diagnostic = _diagnose_runtime_for_request(payload.runtime_key, invalidate=True)
    if not diagnostic.get("ready"):
        raise HTTPException(
            status_code=409,
            detail=diagnostic.get("error") or "Selected Agent is not ready",
        )
    agent_model, reasoning_effort = _resolve_agent_execution(
        diagnostic,
        requested_model=payload.model or payload.codex_model,
        requested_reasoning_effort=payload.reasoning_effort,
    )

    active_jobs = [
        job
        for job in db.scalars(
            select(QueueJob)
            .where(
                QueueJob.job_type == WEBSITE_GAP_JOB_TYPE,
                QueueJob.status.in_(("pending", "running")),
            )
            .order_by(QueueJob.id.desc())
        )
        if int((job.payload_json or {}).get("workspace_id") or 0) == workspace_id
    ]
    same_scope = next(
        (
            job
            for job in active_jobs
            if (job.payload_json or {}).get("input_fingerprint")
            == context["input_fingerprint"]
            and (job.payload_json or {}).get("runtime_key", "local_codex") == payload.runtime_key
            and (job.payload_json or {}).get("model") == agent_model
            and (job.payload_json or {}).get("reasoning_effort") == reasoning_effort
        ),
        None,
    )
    if same_scope is not None:
        return _website_gap_analysis_read(same_scope)

    _assert_agent_capacity(db, workspace_id)
    job = QueueJob(
        job_type=WEBSITE_GAP_JOB_TYPE,
        status="pending",
        priority=26,
        scheduled_at=datetime.now(timezone.utc),
        max_attempts=1,
        payload_json={
            "project_id": 0,
            "workspace_id": workspace_id,
            "batch_id": payload.batch_id,
            "model_keys": selected_models,
            "question_plan_ids": selected_questions,
            "input_fingerprint": context["input_fingerprint"],
            "evidence_count": len(context["evidence"]),
            "official_metrics": context["deterministic_metrics"],
            "skill_name": skill["name"],
            "skill_sha256": skill["sha256"],
            "runtime_key": payload.runtime_key,
            "model": agent_model,
            "reasoning_effort": reasoning_effort,
            "actor_user_id": user.id,
            "stage": "queued",
        },
    )
    db.add(job)
    db.flush()
    db.add(
        GeoActionEvent(
            workspace_id=workspace_id,
            job_id=job.id,
            event_type="website_gap_analysis_queued",
            actor_type="user",
            actor_user_id=user.id,
            detail={
                "batch_id": payload.batch_id,
                "model_keys": selected_models,
                "question_plan_ids": selected_questions,
                "input_fingerprint": context["input_fingerprint"],
                "evidence_count": len(context["evidence"]),
                "skill_name": skill["name"],
                "skill_sha256": skill["sha256"],
                "runtime_key": payload.runtime_key,
                "model": agent_model,
                "reasoning_effort": reasoning_effort,
            },
        )
    )
    db.commit()
    db.refresh(job)
    return _website_gap_analysis_read(job)


@router.get(
    "/workspaces/{workspace_id}/website-gap-analyses/latest",
    response_model=WebsiteGapAnalysisRunRead | None,
)
def get_latest_website_gap_analysis(
    workspace_id: int,
    batch_id: int = Query(ge=1),
    model_key: str | None = Query(default=None, min_length=1, max_length=120),
    question_plan_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    expected_models = [model_key] if model_key else []
    expected_questions = [question_plan_id] if question_plan_id else []
    job = next(
        (
            row
            for row in db.scalars(
                select(QueueJob)
                .where(QueueJob.job_type == WEBSITE_GAP_JOB_TYPE)
                .order_by(QueueJob.id.desc())
                .limit(200)
            )
            if int((row.payload_json or {}).get("workspace_id") or 0) == workspace_id
            and int((row.payload_json or {}).get("batch_id") or 0) == batch_id
            and list((row.payload_json or {}).get("model_keys") or []) == expected_models
            and list((row.payload_json or {}).get("question_plan_ids") or [])
            == expected_questions
        ),
        None,
    )
    return _website_gap_analysis_read(job) if job else None


@router.get(
    "/workspaces/{workspace_id}/website-gap-analyses/{job_id}",
    response_model=WebsiteGapAnalysisRunRead,
)
def get_website_gap_analysis(
    workspace_id: int,
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    job = db.get(QueueJob, job_id)
    if (
        job is None
        or job.job_type != WEBSITE_GAP_JOB_TYPE
        or int((job.payload_json or {}).get("workspace_id") or 0) != workspace_id
    ):
        raise HTTPException(status_code=404, detail="Website gap analysis run not found")
    return _website_gap_analysis_read(job)


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
    action_id: int | None = Query(default=None, ge=1),
    include_legacy: bool = Query(default=True),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    # Direct service calls in tests and workers do not run FastAPI's Query
    # coercion, so normalize its default sentinel before using it as an id.
    if not isinstance(action_id, int):
        action_id = None
    focus_opportunity = None
    if action_id is not None:
        focus_action = scoped_or_404(db, GeoOptimizationAction, workspace_id, action_id)
        if focus_action.opportunity_id:
            focus_opportunity = db.get(GeoActionOpportunity, focus_action.opportunity_id)

    query = select(GeoActionOpportunity).where(
        GeoActionOpportunity.workspace_id == workspace_id,
        GeoActionOpportunity.opportunity_type != "website_scope_gap",
    )
    if not include_legacy:
        query = query.where(
            GeoActionOpportunity.rule_version.in_(
                [AGENT_RULE_VERSION, WEBSITE_GAP_RULE_VERSION, WEBSITE_RULE_VERSION]
            )
        )
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
    # Website citation readiness is an audit finding rather than a model-batch
    # recommendation.  It remains visible under the unfiltered "all" view.
    if model_key or question_plan_id is not None:
        rows = [row for row in rows if row.opportunity_type != "website_citation_readiness"]
    if batch_id is not None:
        rows = [
            row
            for row in rows
            if row.opportunity_type == "website_citation_readiness"
            or int((row.scope_snapshot or {}).get("batch_id") or 0) == batch_id
        ]
    if model_key:
        rows = [
            row
            for row in rows
            if model_key in ((row.scope_snapshot or {}).get("model_keys") or [])
        ]
    if question_plan_id is not None:
        rows = [
            row
            for row in rows
            if int((row.scope_snapshot or {}).get("question_plan_id") or 0)
            == question_plan_id
        ]
    if focus_opportunity is not None and all(row.id != focus_opportunity.id for row in rows):
        rows.insert(0, focus_opportunity)
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
    is_website_audit_action = opportunity.opportunity_type == "website_citation_readiness"
    is_website_action = opportunity.opportunity_type in {
        "website_citation_readiness",
        "website_scope_gap",
    }
    selected_scope = {
        "opportunity_id": opportunity.id,
        "evidence_ids": [link.evidence_id for link in links],
        "question_plan_id": question_plan_id,
        "source_type": (opportunity.scope_snapshot or {}).get("source_type", "model_observation"),
    }
    if is_website_audit_action:
        selected_scope.update(
            {
                "website_audit_id": opportunity.scope_snapshot.get("website_audit_id"),
                "raw_html_sha256": opportunity.scope_snapshot.get("raw_html_sha256"),
                "finding_codes": opportunity.scope_snapshot.get("finding_codes", []),
            }
        )
    action_type, deliverable_type = classify_action_opportunity(opportunity)
    affected_question_ids, affected_model_keys, scope_fingerprint = opportunity_scope_fields(
        db, opportunity
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
        action_type=action_type,
        deliverable_type=deliverable_type,
        workflow_version="action-flow.v2",
        affected_question_ids=affected_question_ids,
        affected_model_keys=affected_model_keys,
        scope_fingerprint=scope_fingerprint,
        measurement_status="not_eligible",
        selected_at=datetime.now(timezone.utc),
    )
    opportunity.status = "selected"
    db.add(action)
    db.flush()
    action_targets = create_opportunity_targets(db, action, opportunity)
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
                "action_type": action.action_type,
                "deliverable_type": action.deliverable_type,
                "target_ids": [target.id for target in action_targets],
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


@router.get("/workspaces/{workspace_id}/actions", response_model=list[ActionRead])
def list_actions(
    workspace_id: int,
    view: str = Query(default="all", pattern="^(all|mine|approvals|overdue_blocked)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    rows = list(
        db.scalars(
            select(GeoOptimizationAction)
            .where(GeoOptimizationAction.workspace_id == workspace_id)
            .order_by(GeoOptimizationAction.id.desc())
        )
    )
    if view == "mine":
        rows = [row for row in rows if row.assignee_user_id == user.id]
    elif view == "approvals":
        rows = [
            row
            for row in rows
            if any(
                approval.status == "pending" and approval.reviewer_user_id == user.id
                for approval in v2_action_approvals(db, row.id)
            )
        ]
    elif view == "overdue_blocked":
        rows = [
            row
            for row in rows
            if row.stage == "blocked"
            or v2_is_past(row.due_at)
            or v2_is_past(row.approval_due_at)
        ]
    return [v2_action_payload(db, row) for row in rows]


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
    run = scoped_or_404(db, GeoObservationRun, workspace_id, payload.run_id)
    evidence = scoped_or_404(db, GeoEvidence, workspace_id, payload.evidence_id)
    if evidence.run_id != run.id:
        raise HTTPException(
            status_code=422, detail="Evidence must belong to the declared re-observation run"
        )
    row = GeoReobservation(
        action_id=action.id,
        workspace_id=workspace_id,
        round_index=int(
            db.scalar(
                select(func.max(GeoReobservation.round_index)).where(
                    GeoReobservation.action_id == action.id
                )
            )
            or 0
        )
        + 1,
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


def _retest_ledger_batch(db: Session, row: GeoReobservation) -> GeoObservationBatch | None:
    retest_ledger_batch = (
        db.get(GeoObservationBatch, row.retest_batch_id) if row.retest_batch_id else None
    )
    if retest_ledger_batch is None and row.retest_queue_job_id:
        retest_ledger_batch = db.scalar(
            select(GeoObservationBatch).where(
                GeoObservationBatch.queue_job_id == row.retest_queue_job_id
            )
        )
    return retest_ledger_batch


def _action_retest_read(db: Session, row: GeoReobservation) -> dict:
    """Read the retest ledger only. GET endpoints must never advance workflow state."""
    target_links = list(
        db.scalars(
            select(GeoReobservationTarget)
            .where(GeoReobservationTarget.reobservation_id == row.id)
            .order_by(GeoReobservationTarget.id.asc())
        )
    )
    retest_ledger_batch = _retest_ledger_batch(db, row)
    batch_summary = (
        _official_api_batch_summary(db, retest_ledger_batch)
        if retest_ledger_batch is not None
        else None
    )
    return {
        "id": row.id,
        "action_id": row.action_id,
        "workspace_id": row.workspace_id,
        "round_index": row.round_index,
        "status": row.status,
        "baseline_batch_id": row.baseline_batch_id,
        "retest_batch_id": row.retest_batch_id,
        "retest_queue_job_id": row.retest_queue_job_id,
        "scope_snapshot": row.scope_snapshot or {},
        "baseline_metrics": row.baseline_metrics or {},
        "retest_metrics": row.retest_metrics or {},
        "conclusion": row.conclusion,
        "measured_delta": row.measured_delta or {},
        "target_evidence": [
            {
                "action_target_id": link.action_target_id,
                "completion_evidence_id": link.completion_evidence_id,
                "evidence_sha256": link.evidence_sha256,
                "scope_fingerprint": link.scope_fingerprint,
            }
            for link in target_links
        ],
        "batch": batch_summary,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
    }


def _refresh_action_retest(db: Session, row: GeoReobservation) -> dict:
    batch_summary = None
    retest_ledger_batch = _retest_ledger_batch(db, row)
    if retest_ledger_batch is not None:
        batch_summary = _official_api_batch_summary(db, retest_ledger_batch)
        if row.status not in {"completed", "failed"}:
            if batch_summary["status"] in {"pending", "running"}:
                row.status = "queued" if batch_summary["status"] == "pending" else "running"
            else:
                baseline_batch = db.get(GeoObservationBatch, row.baseline_batch_id)
                retest_batch = retest_ledger_batch
                scope = row.scope_snapshot or {}
                question_plan_ids = sorted(
                    {
                        int(value)
                        for value in scope.get("question_plan_ids") or []
                        if int(value) > 0
                    }
                )
                question_plan_id = int(scope.get("question_plan_id") or 0)
                if question_plan_id and question_plan_id not in question_plan_ids:
                    question_plan_ids.append(question_plan_id)
                    question_plan_ids.sort()
                provider_ids = [int(value) for value in scope.get("provider_ids") or []]
                action = db.get(GeoOptimizationAction, row.action_id)
                if baseline_batch is None or retest_batch is None or not question_plan_ids or not provider_ids:
                    row.status = "failed"
                    row.conclusion = "insufficient_evidence"
                    row.measured_delta = {
                        "comparable": False,
                        "reason": "retest_scope_or_batch_missing",
                    }
                    if action:
                        action.status = "in_progress"
                        if action.workflow_version == "action-flow.v2":
                            action.measurement_status = "inconclusive"
                        else:
                            action.stage = "retest_failed"
                        action.blocked_reason = "复测范围或观测批次缺失，请重新创建复测。"
                else:
                    baseline_metrics = build_batch_metrics(
                        db,
                        baseline_batch,
                        question_plan_ids=question_plan_ids,
                        provider_ids=provider_ids,
                    )
                    retest_metrics = build_batch_metrics(
                        db,
                        retest_batch,
                        question_plan_ids=question_plan_ids,
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
                    if action:
                        if conclusion in {"improved", "unchanged", "regressed"}:
                            if action.workflow_version == "action-flow.v2":
                                eligible_target_ids = {
                                    target.id
                                    for target in db.scalars(
                                        select(GeoActionTarget).where(
                                            GeoActionTarget.action_id == action.id
                                        )
                                    )
                                    if v2_target_is_final(
                                        action.action_type, target.delivery_status
                                    )
                                    and db.scalar(
                                        select(GeoActionCompletionEvidence.id).where(
                                            GeoActionCompletionEvidence.target_id == target.id,
                                            GeoActionCompletionEvidence.verification_status
                                            == "verified",
                                        )
                                    )
                                }
                                completed_reobservation_ids = list(
                                    db.scalars(
                                        select(GeoReobservation.id).where(
                                            GeoReobservation.action_id == action.id,
                                            GeoReobservation.status == "completed",
                                            GeoReobservation.conclusion.in_(
                                                ("improved", "unchanged", "regressed")
                                            ),
                                        )
                                    )
                                )
                                measured_target_ids = set(
                                    db.scalars(
                                        select(GeoReobservationTarget.action_target_id).where(
                                            GeoReobservationTarget.reobservation_id.in_(
                                                completed_reobservation_ids or [-1]
                                            )
                                        )
                                    )
                                )
                                fully_measured = bool(eligible_target_ids) and (
                                    eligible_target_ids <= measured_target_ids
                                )
                                action.measurement_status = (
                                    "measured" if fully_measured else "partially_measured"
                                )
                                action.status = "verified" if fully_measured else "in_progress"
                            else:
                                action.status = "verified"
                                action.stage = "verified"
                                action.completed_at = row.completed_at
                            action.blocked_reason = None
                            if action.opportunity_id:
                                opportunity = db.get(
                                    GeoActionOpportunity, action.opportunity_id
                                )
                                if opportunity and opportunity.workspace_id == row.workspace_id:
                                    action_rows = list(
                                        db.scalars(
                                            select(GeoReobservation)
                                            .where(GeoReobservation.action_id == action.id)
                                            .order_by(GeoReobservation.round_index)
                                        )
                                    )
                                    outcome = derive_action_outcome(action_rows)
                                    opportunity.status = (
                                        "completed"
                                        if outcome["status"] == "stable_improvement"
                                        else "selected"
                                    )
                        else:
                            action.status = "in_progress"
                            if action.workflow_version == "action-flow.v2":
                                action.measurement_status = "inconclusive"
                            else:
                                action.stage = "retest_inconclusive"
                            action.blocked_reason = "复测已结束，但样本或模型版本不满足同口径比较要求。"
                    db.add(
                        GeoActionEvent(
                            workspace_id=row.workspace_id,
                            action_id=row.action_id,
                            event_type="comparable_retest_completed",
                            from_stage=(
                                action.stage
                                if action and action.workflow_version == "action-flow.v2"
                                else "retesting"
                            ),
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
            if action.workflow_version == "action-flow.v2":
                action.measurement_status = "inconclusive"
            else:
                action.stage = "retest_failed"
            action.blocked_reason = "复测队列记录不存在，请重新创建复测。"
        db.commit()
        db.refresh(row)
    return _action_retest_read(db, row)


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
    row = db.scalar(
        select(GeoReobservation)
        .where(GeoReobservation.action_id == action.id)
        .order_by(GeoReobservation.round_index.desc())
    )
    if row is None:
        raise HTTPException(status_code=404, detail="该行动还没有复测任务")
    return _action_retest_read(db, row)


@router.post(
    "/workspaces/{workspace_id}/actions/{action_id}/retest/refresh",
    response_model=ActionRetestRead,
)
def refresh_action_retest(
    workspace_id: int,
    action_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    action = scoped_or_404(db, GeoOptimizationAction, workspace_id, action_id)
    row = db.scalar(
        select(GeoReobservation)
        .where(GeoReobservation.action_id == action.id)
        .order_by(GeoReobservation.round_index.desc())
    )
    if row is None:
        raise HTTPException(status_code=404, detail="该行动还没有复测任务")
    return _refresh_action_retest(db, row)


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


def _latest_verified_target_evidence(
    db: Session,
    *,
    action: GeoOptimizationAction,
    target: GeoActionTarget,
) -> GeoActionCompletionEvidence | None:
    return db.scalar(
        select(GeoActionCompletionEvidence)
        .where(
            GeoActionCompletionEvidence.workspace_id == action.workspace_id,
            GeoActionCompletionEvidence.action_id == action.id,
            GeoActionCompletionEvidence.target_id == target.id,
            GeoActionCompletionEvidence.verification_status == "verified",
        )
        .order_by(GeoActionCompletionEvidence.id.desc())
    )


def _action_retest_target_evidence(
    db: Session,
    *,
    action: GeoOptimizationAction,
    selected_target_ids: list[int] | None,
) -> list[tuple[GeoActionTarget, GeoActionCompletionEvidence]]:
    targets = list(
        db.scalars(
            select(GeoActionTarget)
            .where(GeoActionTarget.action_id == action.id)
            .order_by(GeoActionTarget.ordinal.asc(), GeoActionTarget.id.asc())
        )
    )
    if not targets:
        return []
    targets_by_id = {target.id: target for target in targets}
    requested_ids = sorted(set(selected_target_ids or []))
    if requested_ids:
        missing_ids = sorted(set(requested_ids) - set(targets_by_id))
        if missing_ids:
            raise HTTPException(status_code=404, detail="部分复测目标不存在或不属于当前行动")
        selected_targets = [targets_by_id[target_id] for target_id in requested_ids]
    else:
        eligible_targets = [
            target
            for target in targets
            if v2_target_is_final(action.action_type, target.delivery_status)
            and _latest_verified_target_evidence(db, action=action, target=target) is not None
        ]
        if not eligible_targets:
            raise HTTPException(status_code=409, detail="当前还没有已完成且证据核验通过的目标")
        if len(eligible_targets) > 1:
            raise HTTPException(status_code=409, detail="多个目标已具备复测条件，请明确选择本轮复测目标")
        selected_targets = eligible_targets

    pairs: list[tuple[GeoActionTarget, GeoActionCompletionEvidence]] = []
    for target in selected_targets:
        if not v2_target_is_final(action.action_type, target.delivery_status):
            raise HTTPException(status_code=409, detail=f"目标“{target.display_name}”尚未真实完成")
        evidence = _latest_verified_target_evidence(db, action=action, target=target)
        if evidence is None:
            raise HTTPException(status_code=409, detail=f"目标“{target.display_name}”缺少核验通过的完成证据")
        pairs.append((target, evidence))
    return pairs


def _create_action_retest_impl(
    workspace_id: int,
    action_id: int,
    db: Session,
    user: User,
    *,
    selected_target_ids: list[int] | None = None,
    idempotency_key: str | None = None,
):
    workspace_or_404(db, user, workspace_id)
    action = scoped_or_404(db, GeoOptimizationAction, workspace_id, action_id)
    existing = db.scalar(
        select(GeoReobservation)
        .where(GeoReobservation.action_id == action.id)
        .order_by(GeoReobservation.round_index.desc())
    )
    requested_target_ids = sorted(set(selected_target_ids or []))
    if existing and idempotency_key:
        existing_scope = existing.scope_snapshot or {}
        if existing_scope.get("idempotency_key") == idempotency_key:
            existing_target_ids = sorted(
                int(value) for value in existing_scope.get("action_target_ids") or []
            )
            if existing_target_ids != requested_target_ids:
                raise HTTPException(status_code=409, detail="同一幂等键不能用于不同的复测目标")
            return _refresh_action_retest(db, existing)
    if existing and existing.status in {"preparing", "queued", "running"}:
        existing_target_ids = sorted(
            int(value)
            for value in (existing.scope_snapshot or {}).get("action_target_ids") or []
        )
        if requested_target_ids and existing_target_ids != requested_target_ids:
            raise HTTPException(status_code=409, detail="已有另一组目标正在复测，请等待本轮结束")
        return _refresh_action_retest(db, existing)

    target_evidence = _action_retest_target_evidence(
        db,
        action=action,
        selected_target_ids=selected_target_ids,
    )

    published_run = None
    if not target_evidence:
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
    if not target_evidence and published_run is None:
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
    question_plan_ids = sorted(
        {
            int(value)
            for value in (action.affected_question_ids or [])
            if int(value) > 0
        }
    )
    if action.question_plan_id and action.question_plan_id not in question_plan_ids:
        question_plan_ids.append(action.question_plan_id)
        question_plan_ids.sort()
    if not question_plan_ids:
        raise HTTPException(status_code=409, detail="行动未关联原始问题，不能创建同口径复测")
    if len(question_plan_ids) > MAX_OFFICIAL_OBSERVATION_QUESTIONS:
        raise HTTPException(
            status_code=409,
            detail=(
                f"单轮复测最多支持 {MAX_OFFICIAL_OBSERVATION_QUESTIONS} 个问题，"
                "请分批执行"
            ),
        )
    configuration = baseline_batch.configuration or {}
    selected_model_keys = list(
        dict.fromkeys(
            str(value).strip()
            for value in (
                action.affected_model_keys
                or (action.baseline_snapshot or {}).get("model_keys")
                or []
            )
            if str(value).strip()
        )
    )
    configured_providers = [
        item for item in configuration.get("providers") or [] if isinstance(item, dict)
    ]
    if selected_model_keys:
        configured_providers = [
            item
            for item in configured_providers
            if str(item.get("model_key") or item.get("key") or "") in selected_model_keys
        ]
        available_model_keys = {
            str(item.get("model_key") or item.get("key") or "")
            for item in configuration.get("providers") or []
            if isinstance(item, dict)
        }
        missing_model_keys = sorted(set(selected_model_keys) - available_model_keys)
        if missing_model_keys:
            raise HTTPException(
                status_code=409,
                detail=f"基线批次缺少原行动选定的模型渠道：{', '.join(missing_model_keys)}",
            )
    provider_ids = [int(item.get("id") or 0) for item in configured_providers if int(item.get("id") or 0) > 0]
    provider_ids = list(dict.fromkeys(provider_ids))
    if not provider_ids:
        raise HTTPException(status_code=409, detail="基线批次没有可复用的模型渠道")
    available_question_ids = {
        int(item.get("id") or 0)
        for item in configuration.get("questions") or []
        if isinstance(item, dict) and int(item.get("id") or 0) > 0
    }
    missing_question_ids = sorted(set(question_plan_ids) - available_question_ids)
    if missing_question_ids:
        raise HTTPException(status_code=409, detail="基线批次缺少本轮行动影响的问题口径")
    baseline_metrics = build_batch_metrics(
        db,
        baseline_batch,
        question_plan_ids=question_plan_ids,
        provider_ids=provider_ids,
    )
    if (
        int(baseline_metrics.get("eligible_samples") or 0) < 1
        or baseline_metrics.get("eligible_samples") != baseline_metrics.get("expected_samples")
    ):
        raise HTTPException(status_code=409, detail="基线样本不满足真实联网证据门槛，不能做可比复测")

    now = datetime.now(timezone.utc)
    opportunity = db.get(GeoActionOpportunity, action.opportunity_id) if action.opportunity_id else None
    if not action.measurement_plan:
        action.measurement_plan = default_measurement_plan(action, opportunity)
    row = GeoReobservation(
        action_id=action.id,
        workspace_id=workspace_id,
        round_index=(existing.round_index + 1) if existing else 1,
    )
    db.add(row)
    row.status = "preparing"
    row.baseline_batch_id = baseline_batch.id
    row.retest_batch_id = None
    row.retest_queue_job_id = None
    scope_fingerprint = str(action.scope_fingerprint or "")
    if target_evidence and len(scope_fingerprint) != 64:
        raise HTTPException(status_code=409, detail="行动缺少可追溯的范围指纹，请先重新确认行动范围")
    row.scope_snapshot = {
        "schema": "target-action-retest/v3" if target_evidence else "comparable-action-retest/v2",
        "question_plan_id": question_plan_ids[0],
        "question_plan_ids": question_plan_ids,
        "provider_ids": provider_ids,
        "model_keys": selected_model_keys,
        "repeat_count": baseline_batch.repeat_count,
        "baseline_batch_id": baseline_batch.id,
        "measurement_plan": action.measurement_plan,
        "idempotency_key": idempotency_key,
        "action_target_ids": [target.id for target, _evidence in target_evidence],
        "completion_evidence_ids": [evidence.id for _target, evidence in target_evidence],
        "scope_fingerprint": scope_fingerprint or None,
        "target_evidence": [
            {
                "action_target_id": target.id,
                "completion_evidence_id": evidence.id,
                "evidence_sha256": evidence.sha256,
                "scope_fingerprint": scope_fingerprint,
            }
            for target, evidence in target_evidence
        ],
    }
    if published_run:
        distribution, publication_targets = published_run
        row.scope_snapshot = {
            **row.scope_snapshot,
            "distribution_run_id": distribution.id,
            "published_targets": [
                {
                    "platform_key": target.platform_key,
                    "public_url": target.public_url,
                    "published_at": target.published_at.isoformat() if target.published_at else None,
                }
                for target in publication_targets
            ],
        }
    row.baseline_metrics = baseline_metrics
    row.retest_metrics = {}
    row.conclusion = "pending"
    row.measured_delta = {}
    row.started_at = now
    row.completed_at = None
    db.flush()
    for target, evidence in target_evidence:
        db.add(
            GeoReobservationTarget(
                workspace_id=workspace_id,
                reobservation_id=row.id,
                action_target_id=target.id,
                completion_evidence_id=evidence.id,
                evidence_sha256=evidence.sha256,
                scope_fingerprint=scope_fingerprint,
            )
        )
    db.flush()
    try:
        batch_receipt = create_provider_web_search_batch(
            workspace_id,
            OfficialApiObservationBatchCreate(
                provider_ids=provider_ids,
                question_plan_ids=question_plan_ids,
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
        if target_evidence:
            action.measurement_status = "inconclusive"
        db.commit()
        raise HTTPException(status_code=500, detail="复测队列已创建，但统一观测账本缺失")
    queue_job_id = int(retest_batch.queue_job_id or 0)
    queue_job = db.get(QueueJob, queue_job_id) if queue_job_id else None
    if queue_job is None or queue_job.job_type != "geo_observation.batch":
        row.status = "failed"
        row.conclusion = "insufficient_evidence"
        row.measured_delta = {"comparable": False, "reason": "queue_job_missing"}
        if target_evidence:
            action.measurement_status = "inconclusive"
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
    if target_evidence:
        action.measurement_status = "retesting"
    else:
        action.stage = "retesting"
    action.blocked_reason = None
    db.add(
        GeoActionEvent(
            workspace_id=workspace_id,
            action_id=action.id,
            event_type="comparable_retest_queued",
            from_stage=previous_stage,
            to_stage=action.stage,
            actor_type="user",
            actor_user_id=user.id,
            job_id=queue_job_id,
            detail={
                "reobservation_id": row.id,
                "round_index": row.round_index,
                "baseline_batch_id": baseline_batch.id,
                "retest_batch_id": retest_batch.id,
                "question_plan_id": question_plan_ids[0],
                "question_plan_ids": question_plan_ids,
                "provider_ids": provider_ids,
                "repeat_count": baseline_batch.repeat_count,
                "action_target_ids": [target.id for target, _evidence in target_evidence],
                "completion_evidence_ids": [evidence.id for _target, evidence in target_evidence],
                "scope_fingerprint": scope_fingerprint or None,
            },
        )
    )
    db.commit()
    db.refresh(row)
    return _action_retest_read(db, row)


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
    return _create_action_retest_impl(workspace_id, action_id, db, user)


@router.post(
    "/workspaces/{workspace_id}/actions/{action_id}/retests",
    response_model=ActionRetestRead,
    status_code=202,
)
def create_target_action_retest(
    workspace_id: int,
    action_id: int,
    payload: ActionRetestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    return _create_action_retest_impl(
        workspace_id,
        action_id,
        db,
        user,
        selected_target_ids=payload.target_ids,
        idempotency_key=payload.idempotency_key,
    )


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
                "opportunity_id": None,
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
