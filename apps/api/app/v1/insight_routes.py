import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import WRITE_ROLES, get_current_user, require_roles
from app.core.config import get_settings
from app.db.session import get_db
from app.models.cleanroom_v1 import (
    GeoCompetitorInsightSnapshot,
    GeoEvidence,
    GeoObservationBatch,
    GeoObservationRun,
    GeoObservationTask,
    GeoQuestionPlan,
    GeoScorecard,
    GeoWorkspace,
)
from app.models.user import User
from app.v1.competitor_comparison import (
    MATCH_RULE_VERSION,
    brand_configs,
    build_competitor_comparison,
)
from app.v1.competitor_insight import CompetitorInsightError, generate_competitor_insight
from app.v1.observation_service import (
    MODEL_LABELS,
    STANDARD_MODELS,
    refresh_observation_ledger_batch as _refresh_observation_ledger_batch,
    write_scorecard,
)
from app.v1.question_analysis import build_question_analysis
from app.v1.route_support import scoped_or_404, workspace_or_404
from app.v1.scoring import SCORING_VERSION, score_evidence
from app.v1.schemas import (
    ActionEvidenceSummaryRead,
    CompetitorComparisonRead,
    CompetitorInsightRead,
    CompetitorInsightRequest,
    DecisionMapRead,
    EvidenceRead,
    QuestionAnalysisRead,
    ScorecardRead,
    SourceMapRead,
    YaoDatasetImport,
    YaoDeepSeekDatasetImport,
    YaoDoubaoDatasetImport,
)
from app.v1.source_map import build_source_map
from app.v1.workspace_routes import _account_for_import, _clear_lease
from app.v1.yao_adapter import normalize_yao_stage1_dataset


router = APIRouter(prefix="/v1", tags=["geo-insights-v1"])


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
    evidence_model_key = "hunyuan" if payload.platform == "yuanbao" else payload.platform
    evidence_model_label = (
        "腾讯混元 · 元宝官方网页端"
        if payload.platform == "yuanbao" and payload.sample_mode == "browser_assisted"
        else MODEL_LABELS[payload.platform]
    )
    if target_run_id is None:
        run = GeoObservationRun(
            workspace_id=workspace_id,
            adapter_key=f"yao-{payload.platform}",
            status="running",
            request_context={
                "schema": "yao-compatible/v1",
                "sample_mode": payload.sample_mode,
                "sample_count": len(payload.samples),
                "observation_surface": (
                    "official_web_ui"
                    if payload.sample_mode == "browser_assisted"
                    else "imported_api_or_manual"
                ),
                "api_equivalence": "not_claimed",
                "observation_group_id": payload.observation_group_id,
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
            "model_key": evidence_model_key,
            "sample_mode": payload.sample_mode,
            "observation_surface": (
                "official_web_ui"
                if payload.sample_mode == "browser_assisted"
                else "imported_api_or_manual"
            ),
            "observation_group_id": payload.observation_group_id,
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
                model_key=evidence_model_key,
                model_label=evidence_model_label,
                prompt_version=payload.prompt_version,
                sample_mode=payload.sample_mode,
                evidence_level=payload.evidence_level,
                collection_method="official_web_ui_observation"
                if payload.sample_mode == "browser_assisted"
                else payload.sample_mode,
                evidence_kind=(
                    "official_web_ui_answer"
                    if payload.sample_mode == "browser_assisted"
                    else "yao_import"
                ),
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
                    "observation_surface": (
                        "official_web_ui"
                        if payload.sample_mode == "browser_assisted"
                        else "imported_api_or_manual"
                    ),
                    "api_equivalence": "not_claimed",
                    "web_product": payload.platform,
                    "observation_group_id": payload.observation_group_id,
                    "conversation_url": sample.conversation_url,
                    "web_ui_context": (
                        sample.web_ui_context.model_dump()
                        if sample.web_ui_context is not None
                        else None
                    ),
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
                provider_label=f"{evidence_model_label} · Yao 导入",
                model_key=evidence_model_key,
                model_label=evidence_model_label,
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
    model_keys: list[str] | None = Query(default=None),
    question_plan_ids: list[int] | None = Query(default=None),
    batch_ids: list[int] | None = Query(default=None),
    limit: int = Query(default=12, ge=1, le=50),
    evidence_limit: int = Query(default=12, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace = workspace_or_404(db, user, workspace_id)
    selected_models = sorted(set(value.strip() for value in (model_keys or []) if value.strip()))
    if model_key and model_key.strip() not in selected_models:
        selected_models.append(model_key.strip())
    selected_questions = sorted(set(value for value in (question_plan_ids or []) if value > 0))
    if question_plan_id is not None and question_plan_id not in selected_questions:
        selected_questions.append(question_plan_id)
    selected_batches = sorted(set(value for value in (batch_ids or []) if value > 0))
    for selected_question in selected_questions:
        scoped_or_404(db, GeoQuestionPlan, workspace_id, selected_question)
    batch_evidence_ids: set[int] | None = None
    if selected_batches:
        valid_batch_count = int(
            db.scalar(
                select(func.count(GeoObservationBatch.id)).where(
                    GeoObservationBatch.workspace_id == workspace_id,
                    GeoObservationBatch.id.in_(selected_batches),
                )
            )
            or 0
        )
        if valid_batch_count != len(selected_batches):
            raise HTTPException(status_code=404, detail="Observation batch not found")
        batch_evidence_ids = {
            int(value)
            for value in db.scalars(
                select(GeoObservationTask.evidence_id).where(
                    GeoObservationTask.workspace_id == workspace_id,
                    GeoObservationTask.batch_id.in_(selected_batches),
                    GeoObservationTask.evidence_id.is_not(None),
                )
            )
        }

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
    if selected_models:
        scoped_query = scoped_query.where(GeoEvidence.model_key.in_(selected_models))
    if selected_questions:
        scoped_query = scoped_query.where(GeoEvidence.question_plan_id.in_(selected_questions))
    if batch_evidence_ids is not None:
        scoped_query = scoped_query.where(GeoEvidence.id.in_(batch_evidence_ids))
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
            "model_key": selected_models[0] if len(selected_models) == 1 else None,
            "model_keys": selected_models,
            "question_plan_id": selected_questions[0] if len(selected_questions) == 1 else None,
            "question_plan_ids": selected_questions,
            "batch_ids": selected_batches,
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
    model_keys: list[str] | None = Query(default=None),
    question_plan_ids: list[int] | None = Query(default=None),
    batch_ids: list[int] | None = Query(default=None),
    evidence_limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace = workspace_or_404(db, user, workspace_id)
    selected_models = sorted(set(value.strip() for value in (model_keys or []) if value.strip()))
    if model_key and model_key.strip() not in selected_models:
        selected_models.append(model_key.strip())
    selected_questions = sorted(set(value for value in (question_plan_ids or []) if value > 0))
    if question_plan_id is not None and question_plan_id not in selected_questions:
        selected_questions.append(question_plan_id)
    selected_batches = sorted(set(value for value in (batch_ids or []) if value > 0))
    for selected_question in selected_questions:
        scoped_or_404(db, GeoQuestionPlan, workspace_id, selected_question)
    batch_evidence_ids: set[int] | None = None
    if selected_batches:
        valid_batch_count = int(db.scalar(select(func.count(GeoObservationBatch.id)).where(GeoObservationBatch.workspace_id == workspace_id, GeoObservationBatch.id.in_(selected_batches))) or 0)
        if valid_batch_count != len(selected_batches):
            raise HTTPException(status_code=404, detail="Observation batch not found")
        batch_evidence_ids = {int(value) for value in db.scalars(select(GeoObservationTask.evidence_id).where(GeoObservationTask.workspace_id == workspace_id, GeoObservationTask.batch_id.in_(selected_batches), GeoObservationTask.evidence_id.is_not(None)))}

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
    if selected_models:
        scoped_query = scoped_query.where(GeoEvidence.model_key.in_(selected_models))
    if selected_questions:
        scoped_query = scoped_query.where(GeoEvidence.question_plan_id.in_(selected_questions))
    if batch_evidence_ids is not None:
        scoped_query = scoped_query.where(GeoEvidence.id.in_(batch_evidence_ids))
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
            "model_key": selected_models[0] if len(selected_models) == 1 else None,
            "model_keys": selected_models,
            "question_plan_id": selected_questions[0] if len(selected_questions) == 1 else None,
            "question_plan_ids": selected_questions,
            "batch_ids": selected_batches,
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
    model_keys: list[str] | None = Query(default=None),
    scope: str = Query("high", pattern=r"^(all|high)$"),
    batch_id: int | None = Query(default=None, ge=1),
    batch_ids: list[int] | None = Query(default=None),
    question_plan_ids: list[int] | None = Query(default=None),
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
    if not isinstance(model_keys, (list, tuple)):
        model_keys = []
    if not isinstance(batch_id, int):
        batch_id = None
    if not isinstance(batch_ids, (list, tuple)):
        batch_ids = []
    if not isinstance(question_plan_ids, (list, tuple)):
        question_plan_ids = []
    selected_models = sorted(set(value.strip() for value in (model_keys or []) if value.strip()))
    if model_key and model_key not in selected_models:
        selected_models.append(model_key)
    selected_batches = sorted(set(value for value in (batch_ids or []) if value > 0))
    if batch_id is not None and batch_id not in selected_batches:
        selected_batches.append(batch_id)
    selected_questions = sorted(set(value for value in (question_plan_ids or []) if value > 0))
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
    if selected_questions:
        available_question_ids = {question.id for question in questions}
        if any(value not in available_question_ids for value in selected_questions):
            raise HTTPException(status_code=404, detail="Question not found")
        questions = [question for question in questions if question.id in selected_questions]
    all_evidence_rows = list(
        db.scalars(
            select(GeoEvidence)
            .where(GeoEvidence.workspace_id == workspace_id)
            .order_by(GeoEvidence.captured_at.desc(), GeoEvidence.id.desc())
        )
    )
    measurement_batch: GeoObservationBatch | None = None
    measurement_batches: list[GeoObservationBatch] = []
    measurement_evidence_ids: set[int] | None = None
    if selected_batches:
        measurement_batches = list(db.scalars(select(GeoObservationBatch).where(GeoObservationBatch.workspace_id == workspace_id, GeoObservationBatch.id.in_(selected_batches))))
        if len(measurement_batches) != len(selected_batches):
            raise HTTPException(status_code=404, detail="Observation batch not found")
        measurement_batch = max(measurement_batches, key=lambda item: item.id)
        measurement_evidence_ids = {
            int(value)
            for value in db.scalars(
                select(GeoObservationTask.evidence_id).where(
                    GeoObservationTask.workspace_id == workspace_id,
                    GeoObservationTask.batch_id.in_(selected_batches),
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
        and (not selected_models or evidence.model_key in selected_models)
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
    models = [
        {"key": key, "label": label}
        for key, label in STANDARD_MODELS
        if not selected_models or key in selected_models or (key == "qianwen" and "qwen" in selected_models)
    ]
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
            "batch_ids": selected_batches,
            "batch_created_at": measurement_batch.created_at if measurement_batch else None,
            "batch_finished_at": measurement_batch.completed_at if measurement_batch else None,
            "measurement_basis": "multi_batch" if len(selected_batches) > 1 else "single_batch" if measurement_batch else "historical_period",
            "model_key": selected_models[0] if len(selected_models) == 1 else None,
            "model_keys": selected_models,
            "question_plan_ids": selected_questions,
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
