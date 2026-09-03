import asyncio
import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import WRITE_ROLES, get_current_user, require_roles
from app.core.config import get_settings
from app.db.session import SessionLocal, get_db
from app.models import QueueJob
from app.models.cleanroom_v1 import (
    GeoActionOpportunity,
    GeoAgentArtifact,
    GeoAgentEvent,
    GeoAgentRun,
    GeoContentAsset,
    GeoContentBrief,
    GeoContentReview,
    GeoOptimizationAction,
    GeoPlatformVariant,
    GeoWebsiteAudit,
)
from app.models.user import User
from app.services.agent_runtime import (
    diagnose_agent_runtime,
    get_agent_runtime,
    list_agent_runtimes,
    sanitize_agent_error,
)
from app.services.codex_agent_runtime import (
    diagnose_local_codex,
    invalidate_local_codex_diagnostic_cache,
)
from app.v1.agent_orchestration import (
    ARTIFACT_ROOT,
    action_evidence_inputs,
    append_agent_event,
    capture_agent_visuals,
)
from app.v1.brand_facts import verified_active_brand_facts
from app.v1.content_delivery_routes import _website_requires_sourced_brand_facts
from app.v1.route_support import scoped_or_404, workspace_or_404
from app.v1.schemas import (
    AgentArtifactRead,
    AgentEventRead,
    AgentRevisionRequest,
    AgentRunCreate,
    AgentRunProgressRead,
    AgentRunRead,
    AgentRuntimeRead,
    AgentRuntimeTestRead,
)
from app.v1.website_gap_agent import WEBSITE_GAP_JOB_TYPE


router = APIRouter(prefix="/v1", tags=["geo-agent-runs-v1"])

API_ROOT = Path(__file__).resolve().parents[2]
AGENT_ARTIFACT_ROOT = API_ROOT / "private_artifacts" / "agent-runs"


ACTIVE_AGENT_RUN_STATUSES = ("queued", "resuming", "running", "cancelling")
KNOWN_CODEX_REASONING_EFFORTS = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
    "ultra",
)


def _agent_capacity(
    db: Session,
    workspace_id: int,
    *,
    exclude_run_id: int | None = None,
) -> tuple[int, int, object | None]:
    limit = max(1, min(int(get_settings().agent_max_concurrent_runs), 10))
    query = select(GeoAgentRun).where(
        GeoAgentRun.workspace_id == workspace_id,
        GeoAgentRun.status.in_(ACTIVE_AGENT_RUN_STATUSES),
    )
    if exclude_run_id is not None:
        query = query.where(GeoAgentRun.id != exclude_run_id)
    active_run_count = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    job_query = select(QueueJob).where(
        QueueJob.job_type.in_(("geo_opportunity.discover", WEBSITE_GAP_JOB_TYPE)),
        QueueJob.status.in_(("pending", "running")),
        QueueJob.payload_json["workspace_id"].as_integer() == workspace_id,
    )
    active_job_count = int(db.scalar(select(func.count()).select_from(job_query.subquery())) or 0)
    active_count = active_run_count + active_job_count
    busy = None
    if active_count >= limit:
        busy = db.scalar(query.order_by(GeoAgentRun.id.desc()).limit(1))
        if busy is None:
            busy = db.scalar(job_query.order_by(QueueJob.id.desc()).limit(1))
    return limit, active_count, busy


def _agent_runtime_diagnostic(
    db: Session,
    workspace_id: int,
    runtime_key: str = "local_codex",
    *,
    invalidate: bool = False,
) -> dict:
    try:
        diagnostic = _diagnose_runtime_for_request(runtime_key, invalidate=invalidate)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent runtime not found") from exc
    limit, active_count, _busy = _agent_capacity(db, workspace_id)
    return {
        **diagnostic,
        "active_run_count": active_count,
        "max_concurrent_runs": limit,
        "capacity_available": active_count < limit,
        "run_timeout_seconds": max(
            60,
            min(int(get_settings().agent_run_timeout_seconds), 3600),
        ),
    }


def _diagnose_runtime_for_request(runtime_key: str, *, invalidate: bool = False) -> dict:
    if runtime_key == "local_codex":
        if invalidate:
            invalidate_local_codex_diagnostic_cache()
        return diagnose_local_codex()
    return diagnose_agent_runtime(runtime_key, invalidate=invalidate)


def _runtime_unavailable_detail(diagnostic: dict, default: str) -> str:
    if diagnostic.get("login_status") == "capacity_busy":
        return "Agent 当前客户端容量繁忙，请等待正在运行的任务结束"
    return str(diagnostic.get("error") or default)


def _resolve_agent_execution(
    diagnostic: dict,
    *,
    requested_model: str | None,
    requested_reasoning_effort: str | None,
) -> tuple[str | None, str | None]:
    model = requested_model or diagnostic.get("default_model")
    available_models = list(diagnostic.get("available_models") or [])
    if model and model not in available_models:
        raise HTTPException(status_code=422, detail="Selected model is not available for this Agent")

    model_option = next(
        (
            item
            for item in list(diagnostic.get("model_options") or [])
            if str(item.get("id") or "") == str(model or "")
        ),
        None,
    )
    if model_option is None:
        supported_efforts = list(KNOWN_CODEX_REASONING_EFFORTS)
        default_effort = diagnostic.get("default_reasoning_effort")
    else:
        supported_efforts = list(model_option.get("supported_reasoning_efforts") or [])
        default_effort = model_option.get("default_reasoning_effort")
    effort = requested_reasoning_effort or default_effort
    if effort and effort not in supported_efforts:
        raise HTTPException(
            status_code=422,
            detail=f"Agent model {model} does not support reasoning effort {effort}",
        )
    return model, effort


def _resolve_codex_execution(
    diagnostic: dict,
    *,
    requested_model: str | None,
    requested_reasoning_effort: str | None,
) -> tuple[str | None, str | None]:
    """Backward-compatible name retained for focused tests and older callers."""

    return _resolve_agent_execution(
        diagnostic,
        requested_model=requested_model,
        requested_reasoning_effort=requested_reasoning_effort,
    )


def _assert_agent_capacity(
    db: Session,
    workspace_id: int,
    *,
    exclude_run_id: int | None = None,
) -> None:
    limit, active_count, busy = _agent_capacity(db, workspace_id, exclude_run_id=exclude_run_id)
    if active_count < limit:
        return
    raise HTTPException(
        status_code=409,
        detail=(
            f"Workspace Agent capacity is busy ({active_count}/{limit}) with run {getattr(busy, 'id', 'unknown')}; "
            "wait for it to finish or interrupt it before starting another run"
        ),
    )


def _active_agent_run_for_action(
    db: Session,
    workspace_id: int,
    action_id: int,
    *,
    exclude_run_id: int | None = None,
) -> GeoAgentRun | None:
    query = select(GeoAgentRun).where(
        GeoAgentRun.workspace_id == workspace_id,
        GeoAgentRun.action_id == action_id,
        GeoAgentRun.status.in_(ACTIVE_AGENT_RUN_STATUSES),
    )
    if exclude_run_id is not None:
        query = query.where(GeoAgentRun.id != exclude_run_id)
    return db.scalar(query.order_by(GeoAgentRun.id.desc()).limit(1))


def _raise_active_agent_run_conflict(active: GeoAgentRun) -> None:
    raise HTTPException(status_code=409, detail=f"Agent run {active.id} is already active")


def _commit_agent_run_transition(
    db: Session,
    run: GeoAgentRun,
    *,
    exclude_run_id: int | None = None,
) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        active = _active_agent_run_for_action(
            db,
            run.workspace_id,
            run.action_id,
            exclude_run_id=exclude_run_id,
        )
        if active is not None:
            _raise_active_agent_run_conflict(active)
        raise


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


@router.get(
    "/workspaces/{workspace_id}/agent-runtimes",
    response_model=list[AgentRuntimeRead],
)
def read_agent_runtimes(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_or_404(db, user, workspace_id)
    limit, active_count, _busy = _agent_capacity(db, workspace_id)
    shared = {
        "active_run_count": active_count,
        "max_concurrent_runs": limit,
        "capacity_available": active_count < limit,
        "run_timeout_seconds": max(60, min(int(get_settings().agent_run_timeout_seconds), 3600)),
    }
    return [{**diagnostic, **shared} for diagnostic in list_agent_runtimes()]


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
    diagnostic = _agent_runtime_diagnostic(db, workspace_id, invalidate=True)
    started = perf_counter()
    if not diagnostic.get("capacity_available"):
        return {
            "ok": False,
            "runtime": diagnostic,
            "latency_ms": int((perf_counter() - started) * 1000),
            "error": "Codex Agent 当前容量已满，请等待正在运行的任务结束",
        }
    if not diagnostic.get("ready"):
        return {
            "ok": False,
            "runtime": diagnostic,
            "latency_ms": int((perf_counter() - started) * 1000),
            "error": _runtime_unavailable_detail(diagnostic, "Codex login is required"),
        }
    import tempfile

    try:
        with tempfile.TemporaryDirectory(prefix="cqyq-codex-runtime-test-") as directory:
            result = get_agent_runtime("local_codex").run_structured(
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
                reasoning_effort=diagnostic.get("default_reasoning_effort"),
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
            "error": sanitize_agent_error(exc),
        }


@router.post(
    "/workspaces/{workspace_id}/agent-runtimes/{runtime_key}/test",
    response_model=AgentRuntimeTestRead,
)
def test_selected_agent_runtime(
    workspace_id: int,
    runtime_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace_or_404(db, user, workspace_id)
    diagnostic = _agent_runtime_diagnostic(
        db,
        workspace_id,
        runtime_key,
        invalidate=True,
    )
    started = perf_counter()
    if not diagnostic.get("capacity_available"):
        return {
            "ok": False,
            "runtime": diagnostic,
            "latency_ms": int((perf_counter() - started) * 1000),
            "error": "Agent 当前容量已满，请等待正在运行的任务结束",
        }
    if not diagnostic.get("ready"):
        return {
            "ok": False,
            "runtime": diagnostic,
            "latency_ms": int((perf_counter() - started) * 1000),
            "error": _runtime_unavailable_detail(diagnostic, "Agent runtime is not ready"),
        }
    import tempfile

    try:
        with tempfile.TemporaryDirectory(prefix=f"cqyq-{runtime_key}-runtime-test-") as directory:
            result = get_agent_runtime(runtime_key).run_structured(
                task_directory=Path(directory),
                prompt="Return JSON confirming that this Agent runtime can complete a structured turn.",
                output_schema={
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                    "additionalProperties": False,
                },
                developer_instructions="Do not read or write files. Return only the requested JSON.",
                model=diagnostic.get("default_model"),
                reasoning_effort=diagnostic.get("default_reasoning_effort"),
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


def _agent_run_session_id(run: GeoAgentRun) -> str | None:
    if run.runtime_key == "local_codex":
        return run.codex_thread_id
    value = (run.result_snapshot or {}).get("agent_session_id")
    return str(value) if value else None


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
    is_website_scope_gap = opportunity.opportunity_type == "website_scope_gap"
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
        if action.question_plan_id is None and not is_website_scope_gap:
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
    active = _active_agent_run_for_action(db, workspace_id, action_id)
    if active:
        _raise_active_agent_run_conflict(active)
    _assert_agent_capacity(db, workspace_id)
    diagnostic = _diagnose_runtime_for_request(payload.runtime_key, invalidate=True)
    if not diagnostic.get("ready"):
        raise HTTPException(
            status_code=409,
            detail=_runtime_unavailable_detail(diagnostic, "Selected Agent is not ready"),
        )
    platforms = list(dict.fromkeys(payload.selected_platforms or _default_agent_platforms(db, action)))
    if not platforms:
        raise HTTPException(status_code=422, detail="Select at least one target platform")
    if (website_audit or is_website_scope_gap) and platforms != ["official_site"]:
        raise HTTPException(
            status_code=422,
            detail="Website actions must generate the official-site draft before external distribution",
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
    model, reasoning_effort = _resolve_agent_execution(
        diagnostic,
        requested_model=payload.model,
        requested_reasoning_effort=payload.reasoning_effort,
    )
    run = GeoAgentRun(
        workspace_id=workspace_id,
        action_id=action_id,
        requested_by_user_id=user.id,
        runtime_key=payload.runtime_key,
        model=model,
        status="queued",
        stage="queued",
        selected_platforms=platforms,
        request_snapshot={
            "action_id": action_id,
            "selected_platforms": platforms,
            "runtime_key": payload.runtime_key,
            "model": model,
            "reasoning_effort": reasoning_effort,
        },
    )
    db.add(run)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        active = _active_agent_run_for_action(db, workspace_id, action_id)
        if active is not None:
            _raise_active_agent_run_conflict(active)
        raise
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
        detail={
            "job_id": job.id,
            "platforms": platforms,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "runtime_key": payload.runtime_key,
            "from_action_stage": previous_stage,
        },
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
    accepted_visual_kinds = {
        "official_page_screenshot",
        "generated_article_image",
        "licensed_web_image",
    }
    manifest_is_verified = bool(manifest_items) and all(
        item.get("quality_gate") == "passed"
        and (artifact := referenced_artifacts.get(int(item.get("artifact_id") or 0))) is not None
        and artifact.artifact_kind in accepted_visual_kinds
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
    if artifact.artifact_kind not in {
        "official_page_screenshot",
        "generated_article_image",
        "licensed_web_image",
    }:
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
    media_type = str((artifact.metadata_json or {}).get("media_type") or "image/png")
    if media_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise HTTPException(status_code=409, detail="Visual artifact media type is invalid")
    return FileResponse(
        artifact_path,
        media_type=media_type,
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
    if run.status not in {"cancelled", "failed"} or not _agent_run_session_id(run):
        raise HTTPException(status_code=409, detail="Only an interrupted/failed run with an Agent session can resume")
    active = _active_agent_run_for_action(db, workspace_id, run.action_id, exclude_run_id=run.id)
    if active is not None:
        _raise_active_agent_run_conflict(active)
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
    _commit_agent_run_transition(db, run, exclude_run_id=run.id)
    append_agent_event(
        db,
        run,
        event_type="resume_queued",
        stage="queued",
        message="已使用原 Agent 会话恢复任务",
        detail={"job_id": job.id, "runtime_key": run.runtime_key},
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
    if run.status != "awaiting_review" or asset.status != "changes_requested" or not _agent_run_session_id(run):
        raise HTTPException(
            status_code=409,
            detail="Only the current rejected draft with an existing Agent session can be revised",
        )
    active = _active_agent_run_for_action(db, workspace_id, run.action_id, exclude_run_id=run.id)
    if active is not None:
        _raise_active_agent_run_conflict(active)
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
    _commit_agent_run_transition(db, run, exclude_run_id=run.id)
    append_agent_event(
        db,
        run,
        event_type="revision_queued",
        stage="queued",
        message="已根据人工意见排队修订；旧版本保留可追溯",
        detail={"job_id": job.id, "source_asset_id": asset.id, "feedback": feedback},
    )
    return run
