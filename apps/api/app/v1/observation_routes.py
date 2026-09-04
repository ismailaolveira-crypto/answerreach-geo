import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.deps import WRITE_ROLES, get_current_user, require_roles
from app.core.config import get_settings
from app.db.session import get_db
from app.models import LLMProvider, LLMProviderTestRun, QueueJob
from app.models.cleanroom_v1 import (
    GeoObservationBatch,
    GeoObservationRun,
    GeoObservationTask,
    GeoQuestionPlan,
    GeoWorkspace,
)
from app.models.user import User
from app.services.auth import consume_security_rate_limit
from app.services.llm_provider import diagnose_provider
from app.services.usage import enforce_monthly_search_budget
from app.services.worker_heartbeat import workspace_worker_is_online
from app.services.workspace_secrets import DEEPSEEK_API_KEY, get_workspace_secret
from app.v1.observation_service import (
    SEARCH_PROVIDER_TYPES,
    STANDARD_MODELS,
    collect_provider_web_search,
    provider_model_key as _provider_model_key,
    provider_model_label as _provider_model_label,
    question_sampling_eligible as _question_sampling_eligible,
)
from app.v1.route_support import scoped_or_404, workspace_or_404
from app.v1.schemas import (
    ObservationLedgerListRead,
    OfficialApiObservationBatchCreate,
    OfficialApiObservationBatchListRead,
    OfficialApiObservationBatchRead,
    OfficialApiObservationJobStatus,
    OfficialApiObservationRequest,
    OfficialApiObservationResponse,
    QueuedOfficialApiObservationResponse,
    StandardObservationRequest,
    StandardObservationResponse,
)


router = APIRouter(prefix="/v1", tags=["geo-observations-v1"])


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


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
    if not workspace_worker_is_online(db, workspace_id):
        raise HTTPException(
            status_code=503,
            detail=(
                "采集服务当前离线，本次任务尚未创建。"
                "请启动当前仓库 Queue Worker，看到采集服务在线后再试。"
            ),
        )
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
        workspace_api_key = (
            get_workspace_secret(db, workspace_id, DEEPSEEK_API_KEY)
            if provider.provider_type == "deepseek_web_search"
            else None
        )
        diagnostic = diagnose_provider(provider, api_key_override=workspace_api_key)
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
    settings = get_settings()
    retry_after = consume_security_rate_limit(
        db,
        scope="observation-batch-create",
        identity=f"{workspace_id}:{user.id}",
        limit=settings.observation_batch_rate_limit_per_hour,
        window=timedelta(hours=1),
    )
    db.commit()
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="观测批次创建过于频繁，请等待现有任务推进后再试",
            headers={"Retry-After": str(retry_after)},
        )
    # PostgreSQL serializes capacity reservations per workspace. Personal mode
    # uses a single SQLite API process and receives the same transactional check.
    db.scalar(
        select(GeoWorkspace.id)
        .where(GeoWorkspace.id == workspace_id)
        .with_for_update()
    )
    active_batches = int(
        db.scalar(
            select(func.count(GeoObservationBatch.id)).where(
                GeoObservationBatch.workspace_id == workspace_id,
                GeoObservationBatch.status.in_(("pending", "running")),
            )
        )
        or 0
    )
    pending_tasks = int(
        db.scalar(
            select(func.count(GeoObservationTask.id)).where(
                GeoObservationTask.workspace_id == workspace_id,
                GeoObservationTask.status.in_(("pending", "running")),
            )
        )
        or 0
    )
    day_started_at = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    daily_tasks = int(
        db.scalar(
            select(func.count(GeoObservationTask.id)).where(
                GeoObservationTask.workspace_id == workspace_id,
                GeoObservationTask.created_at >= day_started_at,
            )
        )
        or 0
    )
    if active_batches >= settings.observation_active_batch_limit:
        raise HTTPException(status_code=409, detail="当前运行中的观测批次已达到上限")
    if pending_tasks + total > settings.observation_pending_task_limit:
        raise HTTPException(status_code=409, detail="当前待处理观测任务已达到工作区容量上限")
    if daily_tasks + total > settings.observation_daily_task_limit:
        raise HTTPException(status_code=429, detail="今日观测任务量已达到工作区上限")
    now = datetime.now(timezone.utc)
    ledger_batch = GeoObservationBatch(
        workspace_id=workspace_id,
        requested_by_user_id=user.id,
        source_type="official_api",
        status="pending",
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
        started_at=None,
    )
    db.add(ledger_batch)
    db.flush()
    batch = QueueJob(
        job_type="geo_observation.batch",
        status="queued",
        priority=0,
        attempts=0,
        max_attempts=1,
        scheduled_at=now,
        started_at=None,
        payload_json={
            "dispatch_enabled": True,
            "dispatch_source": "current_page_submission",
            "workspace_id": workspace_id,
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
    pending_rows: list[tuple[QueueJob, dict, dict, dict, int]] = []
    for repeat_index in range(1, payload.repeat_count + 1):
        for question in question_snapshots:
            for provider in provider_snapshots:
                observation_group_id = observation_groups[(provider["id"], question["id"])]
                child_payload = {
                    "dispatch_enabled": True,
                    "dispatch_source": "current_page_submission",
                    "workspace_id": workspace_id,
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
                pending_rows.append(
                    (child, child_payload, provider, question, repeat_index)
                )
    # A maximum batch contains 5,000 rows. Flush the jobs and tasks in two
    # bounded waves instead of issuing two flushes for every individual sample.
    db.flush()
    pending_tasks: list[tuple[QueueJob, dict, GeoObservationTask]] = []
    for child, child_payload, provider, question, repeat_index in pending_rows:
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
            observation_group_id=str(child_payload["observation_group_id"]),
            status="pending",
        )
        db.add(task)
        pending_tasks.append((child, child_payload, task))
    db.flush()
    for child, child_payload, task in pending_tasks:
        child.payload_json = {**child_payload, "observation_task_id": task.id}
        db.add(child)
        child_job_ids.append(child.id)
    batch.payload_json = {**batch.payload_json, "child_job_ids": child_job_ids}
    db.commit()
    db.refresh(ledger_batch)
    return _official_api_batch_read(db, ledger_batch)


def _observation_task_status(status: str) -> str:
    return "success" if status in {"completed", "succeeded", "success"} else status


def _observation_status_bucket():
    return case(
        (GeoObservationTask.status.in_(("completed", "succeeded", "success")), "success"),
        (GeoObservationTask.status == "running", "running"),
        (GeoObservationTask.status == "failed", "failed"),
        else_="pending",
    )

def _official_api_batch_counts(
    db: Session, batch_ids: list[int]
) -> dict[int, dict[str, int]]:
    counts = {
        batch_id: {"pending": 0, "running": 0, "success": 0, "failed": 0}
        for batch_id in batch_ids
    }
    if not batch_ids:
        return counts
    bucket = _observation_status_bucket()
    rows = db.execute(
        select(
            GeoObservationTask.batch_id,
            bucket.label("status_bucket"),
            func.count(GeoObservationTask.id),
        )
        .where(GeoObservationTask.batch_id.in_(batch_ids))
        .group_by(GeoObservationTask.batch_id, bucket)
    )
    for batch_id, status, count in rows:
        counts[int(batch_id)][str(status)] = int(count)
    return counts


def _official_api_batch_summary(
    db: Session,
    batch: GeoObservationBatch,
    *,
    counts: dict[str, int] | None = None,
    receipt: QueueJob | None = None,
) -> dict:
    if counts is None:
        counts = _official_api_batch_counts(db, [batch.id])[batch.id]
    settled = counts["success"] + counts["failed"]
    total = sum(counts.values()) or int(batch.total_tasks or 0)
    if total and settled >= total:
        status = (
            "success"
            if counts["failed"] == 0
            else "failed"
            if counts["success"] == 0
            else "partial"
        )
    elif counts["running"]:
        status = "running"
    elif counts["pending"]:
        status = "pending"
    elif batch.status in {"failed", "partial"}:
        status = batch.status
    else:
        status = "pending"
    if receipt is None and batch.queue_job_id:
        receipt = db.get(QueueJob, batch.queue_job_id)
    dispatch_enabled = bool(
        receipt is not None
        and dict(receipt.payload_json or {}).get("dispatch_enabled") is True
    )
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
        "dispatch_enabled": dispatch_enabled,
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
    batch_counts = _official_api_batch_counts(db, [batch.id])[batch.id]
    bucket = _observation_status_bucket()

    def grouped_rows(*columns):
        rows = db.execute(
            select(*columns, bucket.label("status_bucket"), func.count(GeoObservationTask.id))
            .where(GeoObservationTask.batch_id == batch.id)
            .group_by(*columns, bucket)
            .order_by(*columns)
        )
        grouped: dict[tuple, dict[str, int]] = {}
        for *identity, status, count in rows:
            grouped.setdefault(tuple(identity), {"pending": 0, "running": 0, "success": 0, "failed": 0})[
                str(status)
            ] = int(count)
        return grouped

    provider_group_rows = grouped_rows(
        GeoObservationTask.provider_id,
        GeoObservationTask.model_key,
        GeoObservationTask.model_label,
    )
    provider_groups = [
        {
            "id": provider_id if provider_id is not None else -(index + 1),
            "key": model_key,
            "label": model_label,
            "total": sum(counts.values()),
            "pending": counts["pending"],
            "running": counts["running"],
            "succeeded": counts["success"],
            "failed": counts["failed"],
        }
        for index, ((provider_id, model_key, model_label), counts) in enumerate(
            provider_group_rows.items()
        )
    ]
    question_group_rows = grouped_rows(
        GeoObservationTask.question_plan_id,
        GeoObservationTask.question_text_snapshot,
    )
    question_groups = [
        {
            "id": question_id,
            "key": str(question_id),
            "label": label,
            "total": sum(counts.values()),
            "pending": counts["pending"],
            "running": counts["running"],
            "succeeded": counts["success"],
            "failed": counts["failed"],
        }
        for (question_id, label), counts in question_group_rows.items()
    ]

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

    task_total = sum(batch_counts.values())
    task_start = (task_page - 1) * task_page_size
    selected_tasks = list(
        db.scalars(
            select(GeoObservationTask)
            .where(GeoObservationTask.batch_id == batch.id)
            .order_by(GeoObservationTask.id)
            .offset(task_start)
            .limit(task_page_size)
        )
    )
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

    evidence_ids = list(
        db.scalars(
            select(GeoObservationTask.evidence_id)
            .where(
                GeoObservationTask.batch_id == batch.id,
                GeoObservationTask.evidence_id.is_not(None),
            )
            .order_by(GeoObservationTask.evidence_id)
        )
    )
    error_value = func.coalesce(GeoObservationTask.error_detail, GeoObservationTask.error_code)
    errors = list(
        db.scalars(
            select(error_value)
            .where(GeoObservationTask.batch_id == batch.id, error_value.is_not(None))
            .distinct()
            .limit(100)
        )
    )
    return {
        **_official_api_batch_summary(db, batch, counts=batch_counts),
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
    batch_counts = _official_api_batch_counts(db, [batch.id for batch in batches])
    receipt_ids = [batch.queue_job_id for batch in batches if batch.queue_job_id is not None]
    receipts = {
        receipt.id: receipt
        for receipt in db.scalars(select(QueueJob).where(QueueJob.id.in_(receipt_ids)))
    }
    return {
        "items": [
            _official_api_batch_summary(
                db,
                batch,
                counts=batch_counts[batch.id],
                receipt=receipts.get(batch.queue_job_id),
            )
            for batch in batches
        ],
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
        "dispatch_enabled": True,
        "dispatch_source": "current_page_submission",
        "workspace_id": workspace_id,
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
    return collect_provider_web_search(
        db,
        workspace_id=workspace_id,
        payload=payload,
        user=user,
    )
