import argparse
import json
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import ArticleDraft, CrawlTask, Project, QueueJob, TargetQuestion
from app.schemas.content import ArticleDraftGenerate
from app.schemas.report import MaturityReportCreate
from app.services.article_workflow import generate_article_draft, review_article_draft
from app.services.crawl_scheduler import run_due_crawl_schedules
from app.services.job_queue import run_next_job
from app.services.maturity_report import (
    create_report_action_goals,
    generate_maturity_report,
    generate_task_competitive_report,
)


STOP = False


def _handle_stop(_signum: int, _frame: object) -> None:
    global STOP
    STOP = True


def _pending_due_count(db, project_id: int | None) -> int:
    stmt = (
        select(func.count())
        .select_from(QueueJob)
        .where(QueueJob.status == "pending")
        .where(QueueJob.scheduled_at <= datetime.now(UTC))
    )
    if project_id is not None:
        stmt = stmt.where(QueueJob.payload_json["project_id"].as_integer() == project_id)
    return int(db.scalar(stmt) or 0)


def _project_ids_from_successful_jobs(db, ran_jobs: list[QueueJob], project_id: int | None) -> list[int]:
    if project_id is not None:
        return [project_id] if any(job.status == "success" for job in ran_jobs) else []
    project_ids: set[int] = set()
    for job in ran_jobs:
        if job.status != "success":
            continue
        task_id = job.payload_json.get("task_id")
        task = db.get(CrawlTask, int(task_id)) if task_id else None
        if task is not None:
            project_ids.add(task.project_id)
    return sorted(project_ids)


def _generate_report_and_drafts(db, project_id: int, *, draft_count: int, task: CrawlTask | None = None) -> dict:
    project = db.get(Project, project_id)
    if project is None:
        return {"project_id": project_id, "error": "Project not found"}
    report_payload = MaturityReportCreate(
        title=f"{project.name} GEO 模型搜索与竞品分析报告 - {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        report_period="每周模型搜索评测自动生成；结果按实际 Provider 类型标注，不等同于网页端搜索存证",
    )
    report = (
        generate_task_competitive_report(db, project, task, report_payload)
        if task is not None and task.schedule_type == "weekly"
        else generate_maturity_report(db, project, report_payload)
    )
    goals = create_report_action_goals(db, project, report)
    drafts: list[dict] = []
    if draft_count > 0:
        question_ids = [
            row[0]
            for row in db.execute(
                select(ArticleDraft.target_question_id)
                .where(ArticleDraft.project_id == project_id)
                .where(ArticleDraft.target_question_id.is_not(None))
            )
            if row[0] is not None
        ]
        questions = list(
            db.scalars(
                select(TargetQuestion)
                .where(TargetQuestion.project_id == project_id)
                .order_by(TargetQuestion.priority.asc(), TargetQuestion.id.asc())
            )
        )
        for question in questions:
            if len(drafts) >= draft_count:
                break
            if question.id in question_ids:
                continue
            draft = generate_article_draft(
                db,
                project,
                ArticleDraftGenerate(
                    target_question_id=question.id,
                    draft_type="continuous_monitor_article",
                    source_context={
                        "source": "crawl_worker",
                        "source_report_id": report.id,
                        "source_report_title": report.title,
                        "topic_source": "continuous_monitor",
                    },
                ),
            )
            review = review_article_draft(db, draft, review_type="ai")
            drafts.append(
                {
                    "draft_id": draft.id,
                    "review_id": review.id,
                    "title": draft.title,
                    "score": review.total_score,
                    "grade": review.grade,
                }
            )
    db.commit()
    return {
        "project_id": project_id,
        "report_id": report.id,
        "report_score": report.total_score,
        "maturity_level": report.maturity_level,
        "action_goal_count": len(goals),
        "drafts": drafts,
    }


def run_once(*, project_id: int | None, max_jobs: int, generate_report: bool, draft_count: int) -> dict:
    with SessionLocal() as db:
        checked_at, tasks = run_due_crawl_schedules(db, project_id=project_id)
        ran_jobs = []
        for _ in range(max_jobs):
            job = run_next_job(db, project_id=project_id)
            if job is None:
                break
            ran_jobs.append(job)
        post_collection: list[dict] = []
        if generate_report:
            for job in ran_jobs:
                if job.status != "success":
                    continue
                task_id = job.payload_json.get("task_id")
                task = db.get(CrawlTask, int(task_id)) if task_id else None
                if task is None:
                    continue
                post_collection.append(
                    _generate_report_and_drafts(
                        db,
                        task.project_id,
                        draft_count=draft_count,
                        task=task,
                    )
                )
        pending_due_count = _pending_due_count(db, project_id)
        return {
            "checked_at": checked_at.isoformat(),
            "project_id": project_id,
            "created_task_ids": [task.id for task in tasks],
            "ran_job_ids": [job.id for job in ran_jobs],
            "success_job_count": sum(1 for job in ran_jobs if job.status == "success"),
            "failed_job_count": sum(1 for job in ran_jobs if job.status == "failed"),
            "pending_due_count": pending_due_count,
            "post_collection": post_collection,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run due GEO crawl schedules and queue jobs.")
    parser.add_argument("--project-id", type=int, default=1, help="Limit worker to one project. Use 0 for all projects.")
    parser.add_argument("--interval-seconds", type=int, default=60, help="Loop sleep interval.")
    parser.add_argument("--max-jobs", type=int, default=10, help="Maximum ready queue jobs per tick.")
    parser.add_argument("--generate-report", action="store_true", help="Generate a maturity report after successful crawl jobs.")
    parser.add_argument("--draft-count", type=int, default=0, help="Drafts to generate and score after a successful report.")
    parser.add_argument("--once", action="store_true", help="Run one tick and exit.")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    project_id = args.project_id if args.project_id > 0 else None
    while True:
        result = run_once(
            project_id=project_id,
            max_jobs=args.max_jobs,
            generate_report=args.generate_report,
            draft_count=max(args.draft_count, 0),
        )
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if args.once or STOP:
            break
        time.sleep(max(args.interval_seconds, 5))


if __name__ == "__main__":
    main()
