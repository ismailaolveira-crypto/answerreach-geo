from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CrawlSchedule, CrawlTask, LLMProvider, LLMProviderTestRun, Project
from app.schemas.search import CrawlScheduleCreate, CrawlScheduleUpdate, CrawlTaskCreate
from app.services.crawl_runner import create_crawl_task
from app.services.job_queue import enqueue_crawl_task_job


def calculate_next_run(schedule_type: str, interval_hours: int, from_time: datetime | None = None) -> datetime:
    base_time = from_time or datetime.now(UTC)
    if schedule_type == "daily":
        return base_time + timedelta(days=1)
    if schedule_type == "weekly":
        return base_time + timedelta(days=7)
    return base_time + timedelta(hours=max(interval_hours, 1))


def _default_schedule_provider_ids(db: Session) -> list[int]:
    provider_ids: list[int] = []
    providers = list(
        db.scalars(
            select(LLMProvider)
            .where(LLMProvider.status == "active")
            .where(LLMProvider.provider_type.not_in(["mock", "browser_observation"]))
            .order_by(LLMProvider.id.asc())
        )
    )
    for provider in providers:
        latest_test = db.scalar(
            select(LLMProviderTestRun)
            .where(LLMProviderTestRun.provider_id == provider.id)
            .order_by(LLMProviderTestRun.created_at.desc(), LLMProviderTestRun.id.desc())
            .limit(1)
        )
        if latest_test is not None and latest_test.ok is True:
            provider_ids.append(provider.id)
    return provider_ids


def create_crawl_schedule(db: Session, project: Project, payload: CrawlScheduleCreate) -> CrawlSchedule:
    now = datetime.now(UTC)
    provider_ids = payload.provider_ids or _default_schedule_provider_ids(db)
    schedule = CrawlSchedule(
        project_id=project.id,
        name=payload.name,
        schedule_type=payload.schedule_type,
        interval_hours=payload.interval_hours,
        provider_ids=provider_ids,
        target_question_ids=payload.target_question_ids,
        keyword_ids=payload.keyword_ids,
        sample_runs_per_prompt=payload.sample_runs_per_prompt,
        status=payload.status,
        next_run_at=now if payload.execute_now else calculate_next_run(
            payload.schedule_type, payload.interval_hours, now
        ),
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    if payload.execute_now and schedule.status == "active":
        task = run_crawl_schedule(db, schedule)
        setattr(schedule, "last_created_task_id", task.id)
    return schedule


def update_crawl_schedule(
    db: Session, schedule: CrawlSchedule, payload: CrawlScheduleUpdate
) -> CrawlSchedule:
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(schedule, field, value)
    if {"schedule_type", "interval_hours", "status"} & set(update_data):
        schedule.next_run_at = calculate_next_run(schedule.schedule_type, schedule.interval_hours)
    db.commit()
    db.refresh(schedule)
    return schedule


def run_crawl_schedule(db: Session, schedule: CrawlSchedule) -> CrawlTask:
    project = db.get(Project, schedule.project_id)
    if project is None:
        raise ValueError("Project not found")

    provider_ids = schedule.provider_ids or _default_schedule_provider_ids(db)
    payload = CrawlTaskCreate(
        task_type="scheduled_batch",
        schedule_type=schedule.schedule_type,
        provider_ids=provider_ids,
        target_question_ids=schedule.target_question_ids,
        keyword_ids=schedule.keyword_ids,
        sample_runs_per_prompt=schedule.sample_runs_per_prompt,
        execute_now=False,
    )
    task = create_crawl_task(db, project, payload)
    enqueue_crawl_task_job(
        db,
        task=task,
        schedule_id=schedule.id,
        target_question_ids=schedule.target_question_ids,
        keyword_ids=schedule.keyword_ids,
    )
    if schedule.provider_ids != provider_ids:
        schedule.provider_ids = provider_ids
    schedule.last_run_at = datetime.now(UTC)
    schedule.next_run_at = calculate_next_run(schedule.schedule_type, schedule.interval_hours)
    db.commit()
    db.refresh(schedule)
    return task


def run_due_crawl_schedules(
    db: Session,
    project_id: int | None = None,
    project_ids: list[int] | None = None,
    now: datetime | None = None,
) -> tuple[datetime, list[CrawlTask]]:
    checked_at = now or datetime.now(UTC)
    stmt = (
        select(CrawlSchedule)
        .where(CrawlSchedule.status == "active")
        .where(CrawlSchedule.next_run_at <= checked_at)
        .order_by(CrawlSchedule.next_run_at.asc())
    )
    if project_id is not None:
        stmt = stmt.where(CrawlSchedule.project_id == project_id)
    elif project_ids is not None:
        if not project_ids:
            return checked_at, []
        stmt = stmt.where(CrawlSchedule.project_id.in_(project_ids))

    tasks: list[CrawlTask] = []
    for schedule in db.scalars(stmt):
        tasks.append(run_crawl_schedule(db, schedule))
    return checked_at, tasks
