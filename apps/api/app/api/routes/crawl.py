from datetime import UTC, datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import WRITE_ROLES, get_project_or_404, require_project_access, require_roles
from app.db.session import get_db
from app.models import (
    AnswerAnalysis,
    CitationSource,
    Company,
    Competitor,
    CrawlResult,
    CrawlSchedule,
    CrawlTask,
    CrawlTaskLog,
    MentionedEntity,
    ContentAsset,
    PlacementRecord,
    Keyword,
    LLMProvider,
    MaturityReport,
    Project,
    TargetQuestion,
    User,
)
from app.schemas.search import (
    BrowserObservationCreate,
    BrowserObservationBulkCreate,
    BrowserObservationBulkRead,
    BrowserObservationRead,
    AnswerAnalysisUpdate,
    CrawlResultDetail,
    CrawlResultRead,
    CrawlScheduleCreate,
    CrawlScheduleRead,
    CrawlScheduleRunResult,
    CrawlScheduleUpdate,
    CrawlTaskCreate,
    CrawlTaskEstimateRead,
    CrawlTaskLogRead,
    CrawlTaskRead,
    ProjectSearchMetrics,
    ProjectSourceDetail,
    ProjectSourceInsight,
)
from app.services.answer_parser import analyze_answer
from app.services.crawl_scheduler import (
    create_crawl_schedule,
    run_crawl_schedule,
    run_due_crawl_schedules,
    update_crawl_schedule,
)
from app.services.crawl_runner import create_crawl_task, estimate_crawl_task, run_crawl_task
from app.services.audit import record_audit_log

router = APIRouter(
    prefix="/projects/{project_id}",
    tags=["crawl"],
    dependencies=[Depends(require_project_access)],
)


def get_task_or_404(db: Session, project_id: int, task_id: int) -> CrawlTask:
    task = db.get(CrawlTask, task_id)
    if task is None or task.project_id != project_id:
        raise HTTPException(status_code=404, detail="Crawl task not found")
    return task


def get_schedule_or_404(db: Session, project_id: int, schedule_id: int) -> CrawlSchedule:
    schedule = db.get(CrawlSchedule, schedule_id)
    if schedule is None or schedule.project_id != project_id:
        raise HTTPException(status_code=404, detail="Crawl schedule not found")
    return schedule


def build_crawl_result_detail(db: Session, result: CrawlResult) -> CrawlResultDetail:
    analysis = db.scalar(
        select(AnswerAnalysis).where(AnswerAnalysis.crawl_result_id == result.id)
    )
    entities = list(
        db.scalars(select(MentionedEntity).where(MentionedEntity.crawl_result_id == result.id))
    )
    sources = list(
        db.scalars(select(CitationSource).where(CitationSource.crawl_result_id == result.id))
    )
    return CrawlResultDetail(
        **CrawlResultRead.model_validate(result).model_dump(),
        analysis=analysis,
        mentioned_entities=[
            {
                "entity_name": item.entity_name,
                "entity_type": item.entity_type,
                "is_company": item.is_company,
                "is_competitor": item.is_competitor,
                "mention_count": item.mention_count,
                "recommendation_rank": item.recommendation_rank,
            }
            for item in entities
        ],
        citation_sources=[
            {
                "source_title": item.source_title,
                "source_url": item.source_url,
                "source_domain": item.source_domain,
                "source_type": item.source_type,
                "is_owned": item.is_owned,
                "is_placed": item.is_placed,
                "crawlable_score": item.crawlable_score,
                "ai_readiness_score": item.ai_readiness_score,
            }
            for item in sources
        ],
    )


def _resolve_browser_observation_provider(db: Session, payload: BrowserObservationCreate) -> int | None:
    provider_id = payload.provider_id
    if provider_id is not None:
        provider = db.get(LLMProvider, provider_id)
        if provider is None or provider.status != "active":
            raise HTTPException(status_code=400, detail="Provider is not active")
        if provider.provider_type != "browser_observation":
            raise HTTPException(status_code=400, detail="Provider must be browser_observation")
        return provider.id

    stmt = (
        select(LLMProvider)
        .where(LLMProvider.provider_type == "browser_observation")
        .where(LLMProvider.status == "active")
    )
    if payload.platform_name:
        provider = db.scalar(
            stmt.where(LLMProvider.cost_rule["platform_name"].as_string() == payload.platform_name)
            .order_by(LLMProvider.id.asc())
            .limit(1)
        )
        if provider is not None:
            return provider.id

    provider = db.scalar(stmt.order_by(LLMProvider.id.asc()).limit(1))
    return provider.id if provider else None


def _validate_browser_observation_links(db: Session, project: Project, payload: BrowserObservationCreate) -> None:
    if payload.target_question_id is not None:
        question = db.get(TargetQuestion, payload.target_question_id)
        if question is None or question.project_id != project.id:
            raise HTTPException(status_code=400, detail="Target question does not belong to project")
    if payload.keyword_id is not None:
        keyword = db.get(Keyword, payload.keyword_id)
        if keyword is None or keyword.project_id != project.id:
            raise HTTPException(status_code=400, detail="Keyword does not belong to project")
    if payload.report_id is not None:
        report = db.get(MaturityReport, payload.report_id)
        if report is None or report.project_id != project.id:
            raise HTTPException(status_code=400, detail="Report does not belong to project")


def _create_browser_observation_result(
    db: Session,
    *,
    project: Project,
    company: Company,
    user: User,
    payload: BrowserObservationCreate,
) -> CrawlResult:
    provider_id = _resolve_browser_observation_provider(db, payload)
    _validate_browser_observation_links(db, project, payload)

    task = CrawlTask(
        project_id=project.id,
        task_type="browser_observation_manual",
        schedule_type="manual",
        provider_ids=[provider_id] if provider_id else [],
        target_question_ids=[payload.target_question_id] if payload.target_question_id else [],
        keyword_ids=[payload.keyword_id] if payload.keyword_id else [],
        status="success",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    db.add(task)
    db.flush()

    result = CrawlResult(
        task_id=task.id,
        project_id=project.id,
        target_question_id=payload.target_question_id,
        keyword_id=payload.keyword_id,
        provider_id=provider_id,
        prompt_text=payload.prompt_text,
        raw_answer=payload.raw_answer,
        answer_summary=payload.answer_summary or payload.raw_answer[:160],
        status="success",
        collected_at=datetime.now(UTC),
    )
    db.add(result)
    db.flush()

    competitors = list(db.scalars(select(Competitor).where(Competitor.project_id == project.id)))
    analysis = analyze_answer(db, result, company, competitors)
    analysis.analysis_json = {
        **(analysis.analysis_json or {}),
        "method": "browser_observation_manual",
        "browser_observation": {
            "report_id": payload.report_id,
            "platform_name": payload.platform_name,
            "observation_url": payload.observation_url,
            "screenshot_url": payload.screenshot_url,
            "observer_name": payload.observer_name,
            "note": payload.note,
        },
    }

    observed_urls = [
        item.strip()
        for item in [payload.observation_url, *payload.source_urls, payload.screenshot_url]
        if item and item.strip()
    ]
    for url in dict.fromkeys(observed_urls):
        domain = urlparse(url).netloc
        db.add(
            CitationSource(
                crawl_result_id=result.id,
                source_title="浏览器观测证据" if url == payload.screenshot_url else None,
                source_url=url,
                source_domain=domain,
                source_type="screenshot" if url == payload.screenshot_url else "browser_observation",
                is_owned=bool(company.website_url and domain and domain in company.website_url),
                crawlable_score=55,
                ai_readiness_score=55,
            )
        )

    db.add(
        CrawlTaskLog(
            task_id=task.id,
            project_id=project.id,
            level="info",
            message="Browser observation recorded",
            detail_json={
                "provider_id": provider_id,
                "report_id": payload.report_id,
                "target_question_id": payload.target_question_id,
                "keyword_id": payload.keyword_id,
                "source_url_count": len(observed_urls),
            },
        )
    )
    record_audit_log(
        db,
        user=user,
        action="browser_observation.create",
        resource_type="crawl_result",
        resource_id=result.id,
        project_id=project.id,
        company_id=project.company_id,
        detail={"task_id": task.id, "provider_id": provider_id, "report_id": payload.report_id},
    )
    return result


@router.post("/crawl-tasks", response_model=CrawlTaskRead, status_code=201)
def create_project_crawl_task(
    project_id: int,
    payload: CrawlTaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> CrawlTask:
    project = get_project_or_404(db, project_id)
    task = create_crawl_task(db, project, payload)
    record_audit_log(
        db,
        user=user,
        action="crawl_task.create",
        resource_type="crawl_task",
        resource_id=task.id,
        project_id=project.id,
        company_id=project.company_id,
        detail={"task_type": task.task_type, "schedule_type": task.schedule_type},
    )
    db.commit()
    return task


@router.post("/browser-observations", response_model=CrawlResultDetail, status_code=201)
def create_project_browser_observation(
    project_id: int,
    payload: BrowserObservationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> CrawlResultDetail:
    project = get_project_or_404(db, project_id)
    company = db.get(Company, project.company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    result = _create_browser_observation_result(db, project=project, company=company, user=user, payload=payload)
    db.commit()
    db.refresh(result)
    return build_crawl_result_detail(db, result)


@router.post("/browser-observations/bulk", response_model=BrowserObservationBulkRead, status_code=201)
def bulk_create_project_browser_observations(
    project_id: int,
    payload: BrowserObservationBulkCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> BrowserObservationBulkRead:
    project = get_project_or_404(db, project_id)
    company = db.get(Company, project.company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    results = [
        _create_browser_observation_result(db, project=project, company=company, user=user, payload=observation)
        for observation in payload.observations
    ]
    db.commit()
    details = []
    for result in results:
        db.refresh(result)
        details.append(build_crawl_result_detail(db, result))
    return BrowserObservationBulkRead(
        created_count=len(details),
        result_ids=[item.id for item in details],
        source_count=sum(len(item.citation_sources) for item in details),
        screenshot_evidence_count=sum(
            1
            for item in details
            for source in item.citation_sources
            if source.get("source_type") == "screenshot"
        ),
        results=details,
    )


@router.get("/browser-observations", response_model=list[BrowserObservationRead])
def list_project_browser_observations(
    project_id: int,
    limit: int = Query(default=10, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[BrowserObservationRead]:
    get_project_or_404(db, project_id)
    results = list(
        db.scalars(
            select(CrawlResult)
            .join(CrawlTask, CrawlTask.id == CrawlResult.task_id)
            .where(CrawlResult.project_id == project_id)
            .where(CrawlTask.task_type == "browser_observation_manual")
            .order_by(CrawlResult.collected_at.desc(), CrawlResult.id.desc())
            .limit(limit)
        )
    )
    if not results:
        return []

    result_ids = [result.id for result in results]
    analyses = {
        item.crawl_result_id: item
        for item in db.scalars(
            select(AnswerAnalysis).where(AnswerAnalysis.crawl_result_id.in_(result_ids))
        )
    }
    source_rows = db.execute(
        select(
            CitationSource.crawl_result_id,
            func.count(CitationSource.id).label("source_count"),
            func.sum(CitationSource.source_type == "screenshot").label("screenshot_evidence_count"),
        )
        .where(CitationSource.crawl_result_id.in_(result_ids))
        .group_by(CitationSource.crawl_result_id)
    ).all()
    source_counts = {
        row.crawl_result_id: {
            "source_count": int(row.source_count or 0),
            "screenshot_evidence_count": int(row.screenshot_evidence_count or 0),
        }
        for row in source_rows
    }
    observations: list[BrowserObservationRead] = []
    for result in results:
        analysis = analyses.get(result.id)
        observation = {}
        if analysis:
            observation = (analysis.analysis_json or {}).get("browser_observation") or {}
        counts = source_counts.get(result.id, {"source_count": 0, "screenshot_evidence_count": 0})
        observations.append(
            BrowserObservationRead(
                **CrawlResultRead.model_validate(result).model_dump(),
                report_id=observation.get("report_id"),
                platform_name=observation.get("platform_name"),
                observation_url=observation.get("observation_url"),
                screenshot_url=observation.get("screenshot_url"),
                observer_name=observation.get("observer_name"),
                note=observation.get("note"),
                source_count=counts["source_count"],
                screenshot_evidence_count=counts["screenshot_evidence_count"],
            )
        )
    return observations


def _score_status(score: int | float | None) -> str:
    value = int(score or 0)
    if value >= 80:
        return "excellent"
    if value >= 70:
        return "good"
    if value >= 50:
        return "needs_optimization"
    return "poor"


def _source_placement_summary(
    source_domain: str | None, source_url: str | None, placements: list[PlacementRecord]
) -> dict[str, int | str | datetime | None]:
    matching = [
        item
        for item in placements
        if item.target_url
        and (
            (source_url and item.target_url == source_url)
            or (source_domain and urlparse(item.target_url).netloc == source_domain)
        )
    ]
    published = [item for item in matching if item.status == "published"]
    latest_placement_at = None
    if matching:
        latest_placement_at = max(
            (item.published_at or item.planned_at or item.created_at for item in matching),
            default=None,
        )
    placement_count = len(matching)
    if placement_count == 0:
        label = "未投放"
    elif placement_count == 1:
        label = "单次投放"
    elif placement_count < 4:
        label = "多次投放"
    else:
        label = "高频投放"
    return {
        "placement_count": placement_count,
        "published_placement_count": len(published),
        "latest_placement_at": latest_placement_at,
        "placement_frequency_label": label,
    }


@router.post("/crawl-tasks/estimate", response_model=CrawlTaskEstimateRead)
def estimate_project_crawl_task(
    project_id: int,
    payload: CrawlTaskCreate,
    db: Session = Depends(get_db),
) -> CrawlTaskEstimateRead:
    project = get_project_or_404(db, project_id)
    return estimate_crawl_task(db, project, payload)


@router.post("/crawl-schedules", response_model=CrawlScheduleRead, status_code=201)
def create_project_crawl_schedule(
    project_id: int,
    payload: CrawlScheduleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> CrawlSchedule:
    project = get_project_or_404(db, project_id)
    schedule = create_crawl_schedule(db, project, payload)
    record_audit_log(
        db,
        user=user,
        action="crawl_schedule.create",
        resource_type="crawl_schedule",
        resource_id=schedule.id,
        project_id=project.id,
        company_id=project.company_id,
        detail={"schedule_type": schedule.schedule_type, "interval_hours": schedule.interval_hours},
    )
    db.commit()
    return schedule


@router.get("/crawl-schedules", response_model=list[CrawlScheduleRead])
def list_project_crawl_schedules(project_id: int, db: Session = Depends(get_db)) -> list[CrawlSchedule]:
    get_project_or_404(db, project_id)
    return list(
        db.scalars(
            select(CrawlSchedule)
            .where(CrawlSchedule.project_id == project_id)
            .order_by(CrawlSchedule.created_at.desc())
        )
    )


@router.patch("/crawl-schedules/{schedule_id}", response_model=CrawlScheduleRead)
def update_project_crawl_schedule(
    project_id: int,
    schedule_id: int,
    payload: CrawlScheduleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> CrawlSchedule:
    project = get_project_or_404(db, project_id)
    schedule = get_schedule_or_404(db, project_id, schedule_id)
    schedule = update_crawl_schedule(db, schedule, payload)
    record_audit_log(
        db,
        user=user,
        action="crawl_schedule.update",
        resource_type="crawl_schedule",
        resource_id=schedule.id,
        project_id=project.id,
        company_id=project.company_id,
        detail={"updated_fields": list(payload.model_dump(exclude_unset=True).keys())},
    )
    db.commit()
    return schedule


@router.post("/crawl-schedules/{schedule_id}/run", response_model=CrawlTaskRead)
def run_project_crawl_schedule(
    project_id: int,
    schedule_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> CrawlTask:
    project = get_project_or_404(db, project_id)
    schedule = get_schedule_or_404(db, project_id, schedule_id)
    task = run_crawl_schedule(db, schedule)
    record_audit_log(
        db,
        user=user,
        action="crawl_schedule.run",
        resource_type="crawl_task",
        resource_id=task.id,
        project_id=project.id,
        company_id=project.company_id,
        detail={"schedule_id": schedule.id},
    )
    db.commit()
    return task


@router.post("/crawl-schedules/run-due", response_model=CrawlScheduleRunResult)
def run_project_due_crawl_schedules(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> CrawlScheduleRunResult:
    project = get_project_or_404(db, project_id)
    checked_at, tasks = run_due_crawl_schedules(db, project_id=project_id)
    record_audit_log(
        db,
        user=user,
        action="crawl_schedule.run_due",
        resource_type="crawl_schedule",
        project_id=project.id,
        company_id=project.company_id,
        detail={"task_ids": [task.id for task in tasks], "checked_at": checked_at.isoformat()},
    )
    db.commit()
    return CrawlScheduleRunResult(
        checked_at=checked_at,
        due_schedule_count=len(tasks),
        task_ids=[task.id for task in tasks],
    )


@router.get("/crawl-tasks", response_model=list[CrawlTaskRead])
def list_project_crawl_tasks(project_id: int, db: Session = Depends(get_db)) -> list[CrawlTask]:
    get_project_or_404(db, project_id)
    return list(
        db.scalars(
            select(CrawlTask)
            .where(CrawlTask.project_id == project_id)
            .order_by(CrawlTask.created_at.desc())
        )
    )


@router.get("/crawl-tasks/{task_id}", response_model=CrawlTaskRead)
def get_project_crawl_task(project_id: int, task_id: int, db: Session = Depends(get_db)) -> CrawlTask:
    get_project_or_404(db, project_id)
    return get_task_or_404(db, project_id, task_id)


@router.post("/crawl-tasks/{task_id}/retry", response_model=CrawlTaskRead)
def retry_project_crawl_task(
    project_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> CrawlTask:
    project = get_project_or_404(db, project_id)
    task = get_task_or_404(db, project_id, task_id)
    task.error_message = None
    db.commit()
    task = run_crawl_task(
        db,
        task,
        CrawlTaskCreate(
            task_type=task.task_type,
            schedule_type=task.schedule_type,
            provider_ids=task.provider_ids,
            target_question_ids=task.target_question_ids,
            keyword_ids=task.keyword_ids,
            execute_now=False,
        ),
    )
    record_audit_log(
        db,
        user=user,
        action="crawl_task.retry",
        resource_type="crawl_task",
        resource_id=task.id,
        project_id=project.id,
        company_id=project.company_id,
        detail={"status": task.status},
    )
    db.commit()
    return task


@router.get("/crawl-tasks/{task_id}/logs", response_model=list[CrawlTaskLogRead])
def list_project_crawl_task_logs(
    project_id: int, task_id: int, db: Session = Depends(get_db)
) -> list[CrawlTaskLog]:
    get_project_or_404(db, project_id)
    get_task_or_404(db, project_id, task_id)
    return list(
        db.scalars(
            select(CrawlTaskLog)
            .where(CrawlTaskLog.project_id == project_id)
            .where(CrawlTaskLog.task_id == task_id)
            .order_by(CrawlTaskLog.created_at.asc())
        )
    )


@router.get("/crawl-results", response_model=list[CrawlResultRead])
def list_project_crawl_results(
    project_id: int,
    task_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[CrawlResult]:
    get_project_or_404(db, project_id)
    stmt = select(CrawlResult).where(CrawlResult.project_id == project_id)
    if task_id is not None:
        stmt = stmt.where(CrawlResult.task_id == task_id)
    return list(
        db.scalars(
            stmt.order_by(CrawlResult.collected_at.desc())
        )
    )


@router.get("/crawl-results/{result_id}", response_model=CrawlResultDetail)
def get_project_crawl_result(
    project_id: int, result_id: int, db: Session = Depends(get_db)
) -> CrawlResultDetail:
    result = db.get(CrawlResult, result_id)
    if result is None or result.project_id != project_id:
        raise HTTPException(status_code=404, detail="Crawl result not found")
    return build_crawl_result_detail(db, result)


@router.patch("/crawl-results/{result_id}/analysis", response_model=CrawlResultDetail)
def update_project_crawl_result_analysis(
    project_id: int,
    result_id: int,
    payload: AnswerAnalysisUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> CrawlResultDetail:
    project = get_project_or_404(db, project_id)
    result = db.get(CrawlResult, result_id)
    if result is None or result.project_id != project_id:
        raise HTTPException(status_code=404, detail="Crawl result not found")
    analysis = db.scalar(select(AnswerAnalysis).where(AnswerAnalysis.crawl_result_id == result.id))
    if analysis is None:
        analysis = AnswerAnalysis(
            crawl_result_id=result.id,
            company_mentioned=False,
            company_recommended=False,
            company_rank=None,
            sentiment="neutral",
            confidence=0,
            analysis_json={},
        )
        db.add(analysis)
        db.flush()
    previous = {
        "company_mentioned": analysis.company_mentioned,
        "company_recommended": analysis.company_recommended,
        "company_rank": analysis.company_rank,
        "sentiment": analysis.sentiment,
        "confidence": analysis.confidence,
    }
    update_data = payload.model_dump(exclude_unset=True)
    correction_note = update_data.pop("correction_note", None)
    for field, value in update_data.items():
        setattr(analysis, field, value)
    analysis_json = dict(analysis.analysis_json or {})
    analysis_json["manual_correction"] = {
        "corrected_by_user_id": user.id,
        "corrected_by_email": user.email,
        "corrected_at": datetime.now(UTC).isoformat(),
        "previous": previous,
        "note": correction_note,
    }
    analysis.analysis_json = analysis_json
    record_audit_log(
        db,
        user=user,
        action="crawl_result.analysis.correct",
        resource_type="crawl_result",
        resource_id=result.id,
        project_id=project.id,
        company_id=project.company_id,
        detail={"previous": previous, "updated": update_data, "note": correction_note},
    )
    db.commit()
    db.refresh(result)
    return build_crawl_result_detail(db, result)


@router.get("/search-metrics", response_model=ProjectSearchMetrics)
def get_project_search_metrics(project_id: int, db: Session = Depends(get_db)) -> ProjectSearchMetrics:
    get_project_or_404(db, project_id)
    total_answers = (
        db.scalar(select(func.count()).select_from(CrawlResult).where(CrawlResult.project_id == project_id))
        or 0
    )
    company_mentions = (
        db.scalar(
            select(func.count())
            .select_from(AnswerAnalysis)
            .join(CrawlResult, CrawlResult.id == AnswerAnalysis.crawl_result_id)
            .where(CrawlResult.project_id == project_id)
            .where(AnswerAnalysis.company_mentioned.is_(True))
        )
        or 0
    )
    company_recommendations = (
        db.scalar(
            select(func.count())
            .select_from(AnswerAnalysis)
            .join(CrawlResult, CrawlResult.id == AnswerAnalysis.crawl_result_id)
            .where(CrawlResult.project_id == project_id)
            .where(AnswerAnalysis.company_recommended.is_(True))
        )
        or 0
    )
    competitor_mentions = (
        db.scalar(
            select(func.count())
            .select_from(MentionedEntity)
            .join(CrawlResult, CrawlResult.id == MentionedEntity.crawl_result_id)
            .where(CrawlResult.project_id == project_id)
            .where(MentionedEntity.is_competitor.is_(True))
        )
        or 0
    )
    top_competitors_rows = db.execute(
        select(MentionedEntity.entity_name, func.sum(MentionedEntity.mention_count).label("mentions"))
        .join(CrawlResult, CrawlResult.id == MentionedEntity.crawl_result_id)
        .where(CrawlResult.project_id == project_id)
        .where(MentionedEntity.is_competitor.is_(True))
        .group_by(MentionedEntity.entity_name)
        .order_by(func.sum(MentionedEntity.mention_count).desc())
        .limit(5)
    ).all()
    provider_rows = db.execute(
        select(CrawlResult.provider_id, func.count(CrawlResult.id).label("answers"))
        .where(CrawlResult.project_id == project_id)
        .group_by(CrawlResult.provider_id)
    ).all()

    denominator = total_answers or 1
    return ProjectSearchMetrics(
        project_id=project_id,
        total_answers=total_answers,
        company_mentions=company_mentions,
        company_recommendations=company_recommendations,
        competitor_mentions=competitor_mentions,
        company_mention_rate=round(company_mentions / denominator, 4),
        company_recommendation_rate=round(company_recommendations / denominator, 4),
        competitor_mention_rate=round(competitor_mentions / denominator, 4),
        top_competitors=[
            {"name": row.entity_name, "mentions": int(row.mentions or 0)}
            for row in top_competitors_rows
        ],
        provider_breakdown=[
            {"provider_id": row.provider_id, "answers": int(row.answers or 0)}
            for row in provider_rows
        ],
    )


@router.get("/source-insights", response_model=list[ProjectSourceInsight])
def list_project_source_insights(
    project_id: int, db: Session = Depends(get_db)
) -> list[ProjectSourceInsight]:
    get_project_or_404(db, project_id)
    sources = list(
        db.scalars(
            select(CitationSource)
            .join(CrawlResult, CrawlResult.id == CitationSource.crawl_result_id)
            .where(CrawlResult.project_id == project_id)
            .order_by(CitationSource.created_at.desc())
        )
    )
    assets = list(
        db.scalars(select(ContentAsset).where(ContentAsset.project_id == project_id))
    )
    placements = list(
        db.scalars(select(PlacementRecord).where(PlacementRecord.project_id == project_id))
    )
    asset_domains = {
        urlparse(asset.source_url).netloc
        for asset in assets
        if asset.source_url and urlparse(asset.source_url).netloc
    }
    grouped: dict[tuple[str | None, str | None], ProjectSourceInsight] = {}
    for source in sources:
        key = (source.source_domain, source.source_url)
        existing = grouped.get(key)
        has_asset = bool(source.source_domain and source.source_domain in asset_domains)
        placement_summary = _source_placement_summary(source.source_domain, source.source_url, placements)
        is_placed = source.is_placed or placement_summary["placement_count"] > 0
        if existing:
            existing.appearances += 1
            existing.is_placed = existing.is_placed or is_placed
            existing.has_content_asset = existing.has_content_asset or has_asset
            existing.placement_count = max(existing.placement_count, int(placement_summary["placement_count"]))
            existing.published_placement_count = max(
                existing.published_placement_count, int(placement_summary["published_placement_count"])
            )
            latest_placement_at = placement_summary["latest_placement_at"]
            if latest_placement_at and (
                existing.latest_placement_at is None or latest_placement_at > existing.latest_placement_at
            ):
                existing.latest_placement_at = latest_placement_at
                existing.placement_frequency_label = str(placement_summary["placement_frequency_label"])
            existing.crawlable_score = max(existing.crawlable_score, source.crawlable_score)
            existing.ai_readiness_score = max(existing.ai_readiness_score, source.ai_readiness_score)
            existing.ai_readiness_status = _score_status(existing.ai_readiness_score)
            existing.crawlability_status = _score_status(existing.crawlable_score)
        else:
            grouped[key] = ProjectSourceInsight(
                source_domain=source.source_domain,
                source_url=source.source_url,
                source_type=source.source_type,
                appearances=1,
                is_owned=source.is_owned,
                is_placed=is_placed,
                has_content_asset=has_asset,
                placement_count=int(placement_summary["placement_count"]),
                published_placement_count=int(placement_summary["published_placement_count"]),
                latest_placement_at=placement_summary["latest_placement_at"],
                placement_frequency_label=str(placement_summary["placement_frequency_label"]),
                ai_readiness_status=_score_status(source.ai_readiness_score),
                crawlability_status=_score_status(source.crawlable_score),
                crawlable_score=source.crawlable_score,
                ai_readiness_score=source.ai_readiness_score,
            )
    return sorted(grouped.values(), key=lambda item: item.appearances, reverse=True)


@router.get("/source-insights/detail", response_model=ProjectSourceDetail)
def get_project_source_detail(
    project_id: int,
    source_url: str | None = Query(default=None),
    source_domain: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> ProjectSourceDetail:
    get_project_or_404(db, project_id)
    if not source_url and not source_domain:
        raise HTTPException(status_code=400, detail="source_url or source_domain is required")

    if source_url and not source_domain:
        source_domain = urlparse(source_url).netloc or None

    source_stmt = (
        select(CitationSource)
        .join(CrawlResult, CrawlResult.id == CitationSource.crawl_result_id)
        .where(CrawlResult.project_id == project_id)
    )
    if source_url:
        source_stmt = source_stmt.where(CitationSource.source_url == source_url)
    elif source_domain:
        source_stmt = source_stmt.where(CitationSource.source_domain == source_domain)

    sources = list(db.scalars(source_stmt.order_by(CitationSource.created_at.desc())))
    if not sources:
        raise HTTPException(status_code=404, detail="Source insight not found")

    placements = list(
        db.scalars(select(PlacementRecord).where(PlacementRecord.project_id == project_id))
    )
    assets = list(db.scalars(select(ContentAsset).where(ContentAsset.project_id == project_id)))
    matching_placements = [
        item
        for item in placements
        if item.target_url
        and (
            (source_url and item.target_url == source_url)
            or (source_domain and urlparse(item.target_url).netloc == source_domain)
        )
    ]
    matching_assets = [
        item
        for item in assets
        if item.source_url
        and (
            (source_url and item.source_url == source_url)
            or (source_domain and urlparse(item.source_url).netloc == source_domain)
        )
    ]
    evidence_results = []
    for source in sources[:20]:
        result = db.get(CrawlResult, source.crawl_result_id)
        if result:
            evidence_results.append(
                {
                    "crawl_result_id": result.id,
                    "prompt_text": result.prompt_text,
                    "answer_summary": result.answer_summary,
                    "collected_at": result.collected_at,
                }
            )

    source = sources[0]
    appearances = len(sources)
    is_placed = source.is_placed or bool(matching_placements)
    has_asset = bool(matching_assets)
    placement_summary = _source_placement_summary(source.source_domain, source.source_url, placements)
    recommendations = []
    if not has_asset:
        recommendations.append("为该信源建立内容资产记录，补充标题、正文摘要、发布渠道和目标 URL。")
    if not is_placed:
        recommendations.append("如果该信源属于可控或可投放渠道，建议创建投放记录并标记发布时间。")
    if source.ai_readiness_score < 70:
        recommendations.append("优化页面结构，增加摘要、小标题、FAQ、列表和明确实体名，提高 AI 可摘录性。")
    if source.crawlable_score < 70:
        recommendations.append("检查页面是否可访问、是否需要登录、是否被 robots 或脚本渲染限制。")
    if appearances >= 3:
        recommendations.append("该信源已多次出现在 AI 答案线索中，建议优先纳入 GEO 运营复盘。")

    return ProjectSourceDetail(
        insight=ProjectSourceInsight(
            source_domain=source.source_domain,
            source_url=source.source_url,
            source_type=source.source_type,
            appearances=appearances,
            is_owned=source.is_owned,
            is_placed=is_placed,
            has_content_asset=has_asset,
            placement_count=int(placement_summary["placement_count"]),
            published_placement_count=int(placement_summary["published_placement_count"]),
            latest_placement_at=placement_summary["latest_placement_at"],
            placement_frequency_label=str(placement_summary["placement_frequency_label"]),
            ai_readiness_status=_score_status(max(item.ai_readiness_score for item in sources)),
            crawlability_status=_score_status(max(item.crawlable_score for item in sources)),
            crawlable_score=max(item.crawlable_score for item in sources),
            ai_readiness_score=max(item.ai_readiness_score for item in sources),
        ),
        evidence_results=evidence_results,
        matching_content_assets=[
            {
                "id": item.id,
                "title": item.title,
                "content_type": item.content_type,
                "source_url": item.source_url,
                "status": item.status,
            }
            for item in matching_assets
        ],
        matching_placements=[
            {
                "id": item.id,
                "channel": item.channel,
                "target_url": item.target_url,
                "status": item.status,
                "published_at": item.published_at,
            }
            for item in matching_placements
        ],
        recommendations=recommendations,
    )
