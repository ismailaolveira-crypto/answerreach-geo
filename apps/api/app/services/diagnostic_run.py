from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CrawlResult, Project
from app.schemas.report import DiagnosticRunCreate, DiagnosticRunResult, MaturityReportCreate
from app.schemas.search import CrawlTaskCreate
from app.services.crawl_runner import estimate_crawl_task, create_crawl_task
from app.services.maturity_report import create_report_action_goals, generate_maturity_report


def run_project_diagnostic(
    db: Session,
    project: Project,
    payload: DiagnosticRunCreate,
) -> DiagnosticRunResult:
    crawl_payload = CrawlTaskCreate(
        task_type="maturity_diagnostic",
        schedule_type="manual",
        provider_ids=payload.provider_ids,
        target_question_ids=payload.target_question_ids,
        keyword_ids=payload.keyword_ids,
        execute_now=payload.execute_now,
        max_estimated_cost=payload.max_estimated_cost,
        allow_over_budget=payload.allow_over_budget,
    )
    estimate = estimate_crawl_task(db, project, crawl_payload)
    task = create_crawl_task(db, project, crawl_payload)
    result_count = (
        db.scalar(select(func.count()).select_from(CrawlResult).where(CrawlResult.task_id == task.id))
        or 0
    )

    report = None
    action_goal_count = 0
    delivery_readiness = {}
    blockers = list(estimate.blockers)
    if task.status == "failed" and task.error_message:
        blockers.append(task.error_message)

    if payload.generate_report and task.status == "success":
        report = generate_maturity_report(
            db,
            project,
            MaturityReportCreate(title=payload.title, report_period=payload.report_period),
        )
        delivery_readiness = (report.report_json or {}).get("delivery_readiness") or {}
        if payload.create_action_goals:
            action_goals = create_report_action_goals(db, project, report)
            action_goal_count = len(action_goals)
            db.commit()

    return DiagnosticRunResult(
        task_id=task.id,
        task_status=task.status,
        task_url=f"/projects/{project.id}/tasks/{task.id}",
        report_id=report.id if report else None,
        report_url=f"/projects/{project.id}/reports/{report.id}" if report else None,
        action_goal_count=action_goal_count,
        provider_count=estimate.provider_count,
        target_question_count=estimate.target_question_count,
        keyword_count=estimate.keyword_count,
        prompt_count=estimate.prompt_count,
        expected_call_count=estimate.total_call_count,
        estimated_total_tokens=estimate.estimated_total_tokens,
        estimated_cost=estimate.estimated_cost,
        currency=estimate.currency,
        result_count=result_count,
        delivery_readiness_status=delivery_readiness.get("status"),
        delivery_readiness_score=delivery_readiness.get("score"),
        warnings=estimate.warnings,
        blockers=blockers,
    )
