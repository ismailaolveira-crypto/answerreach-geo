from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import WRITE_ROLES, get_project_or_404, require_project_access, require_roles
from app.db.session import get_db
from app.models import MaturityReport, MaturityScoreItem, User
from app.schemas.project import ProjectStageGoalRead
from app.schemas.report import (
    DiagnosticRunCreate,
    DiagnosticRunResult,
    MaturityReportCompare,
    MaturityReportCreate,
    MaturityReportDetail,
    MaturityReportRead,
)
from app.services.diagnostic_run import run_project_diagnostic
from app.services.maturity_report import (
    compare_maturity_reports,
    create_report_action_goals,
    generate_maturity_report,
    render_report_markdown,
    render_report_pdf,
)
from app.services.project_goals import goal_suggested_actions
from app.services.audit import record_audit_log

router = APIRouter(
    prefix="/projects/{project_id}",
    tags=["maturity-reports"],
    dependencies=[Depends(require_project_access)],
)


@router.post("/maturity-reports/generate", response_model=MaturityReportRead, status_code=201)
def create_maturity_report(
    project_id: int,
    payload: MaturityReportCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> MaturityReport:
    project = get_project_or_404(db, project_id)
    report = generate_maturity_report(db, project, payload)
    record_audit_log(
        db,
        user=user,
        action="maturity_report.generate",
        resource_type="maturity_report",
        resource_id=report.id,
        project_id=project.id,
        company_id=project.company_id,
        detail={"total_score": report.total_score, "maturity_level": report.maturity_level},
    )
    db.commit()
    return report


@router.post("/diagnostic-runs", response_model=DiagnosticRunResult, status_code=201)
def create_project_diagnostic_run(
    project_id: int,
    payload: DiagnosticRunCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> DiagnosticRunResult:
    project = get_project_or_404(db, project_id)
    result = run_project_diagnostic(db, project, payload)
    record_audit_log(
        db,
        user=user,
        action="diagnostic_run.create",
        resource_type="crawl_task",
        resource_id=result.task_id,
        project_id=project.id,
        company_id=project.company_id,
        detail={
            "task_status": result.task_status,
            "report_id": result.report_id,
            "action_goal_count": result.action_goal_count,
            "provider_count": result.provider_count,
            "target_question_count": result.target_question_count,
            "keyword_count": result.keyword_count,
            "prompt_count": result.prompt_count,
            "expected_call_count": result.expected_call_count,
            "result_count": result.result_count,
            "delivery_readiness_status": result.delivery_readiness_status,
        },
    )
    db.commit()
    return result


@router.get("/maturity-reports", response_model=list[MaturityReportRead])
def list_maturity_reports(project_id: int, db: Session = Depends(get_db)) -> list[MaturityReport]:
    get_project_or_404(db, project_id)
    return list(
        db.scalars(
            select(MaturityReport)
            .where(MaturityReport.project_id == project_id)
            .order_by(MaturityReport.generated_at.desc())
        )
    )


@router.get("/maturity-reports/compare", response_model=MaturityReportCompare)
def compare_project_maturity_reports(
    project_id: int,
    base_report_id: int | None = None,
    target_report_id: int | None = None,
    db: Session = Depends(get_db),
) -> dict:
    project = get_project_or_404(db, project_id)
    if base_report_id is not None and target_report_id is not None:
        base_report = db.get(MaturityReport, base_report_id)
        target_report = db.get(MaturityReport, target_report_id)
        if (
            base_report is None
            or target_report is None
            or base_report.project_id != project_id
            or target_report.project_id != project_id
        ):
            raise HTTPException(status_code=404, detail="Maturity report not found")
    else:
        reports = list(
            db.scalars(
                select(MaturityReport)
                .where(MaturityReport.project_id == project_id)
                .order_by(MaturityReport.generated_at.desc())
                .limit(2)
            )
        )
        if len(reports) < 2:
            raise HTTPException(status_code=400, detail="At least two reports are required")
        target_report, base_report = reports[0], reports[1]

    return compare_maturity_reports(db, project, base_report, target_report)


@router.get("/maturity-reports/{report_id}", response_model=MaturityReportDetail)
def get_maturity_report(
    project_id: int, report_id: int, db: Session = Depends(get_db)
) -> MaturityReportDetail:
    report = db.get(MaturityReport, report_id)
    if report is None or report.project_id != project_id:
        raise HTTPException(status_code=404, detail="Maturity report not found")
    items = list(
        db.scalars(
            select(MaturityScoreItem)
            .where(MaturityScoreItem.report_id == report_id)
            .order_by(MaturityScoreItem.id.asc())
        )
    )
    return MaturityReportDetail(
        **MaturityReportRead.model_validate(report).model_dump(), score_items=items
    )


@router.get("/maturity-reports/{report_id}/export/markdown", response_class=PlainTextResponse)
def export_maturity_report_markdown(
    project_id: int, report_id: int, db: Session = Depends(get_db)
) -> str:
    report = db.get(MaturityReport, report_id)
    if report is None or report.project_id != project_id:
        raise HTTPException(status_code=404, detail="Maturity report not found")
    items = list(
        db.scalars(
            select(MaturityScoreItem)
            .where(MaturityScoreItem.report_id == report_id)
            .order_by(MaturityScoreItem.id.asc())
        )
    )
    return render_report_markdown(report, items)


@router.get("/maturity-reports/{report_id}/export/pdf")
def export_maturity_report_pdf(
    project_id: int, report_id: int, db: Session = Depends(get_db)
) -> Response:
    report = db.get(MaturityReport, report_id)
    if report is None or report.project_id != project_id:
        raise HTTPException(status_code=404, detail="Maturity report not found")
    items = list(
        db.scalars(
            select(MaturityScoreItem)
            .where(MaturityScoreItem.report_id == report_id)
            .order_by(MaturityScoreItem.id.asc())
        )
    )
    pdf = render_report_pdf(report, items)
    filename = f"geo-maturity-report-{report_id}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/maturity-reports/{report_id}/action-goals", response_model=list[ProjectStageGoalRead])
def create_maturity_report_action_goals(
    project_id: int,
    report_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> list[ProjectStageGoalRead]:
    project = get_project_or_404(db, project_id)
    report = db.get(MaturityReport, report_id)
    if report is None or report.project_id != project_id:
        raise HTTPException(status_code=404, detail="Maturity report not found")
    goals = create_report_action_goals(db, project, report)
    for goal in goals:
        record_audit_log(
            db,
            user=user,
            action="maturity_report.action_goal.create",
            resource_type="project_stage_goal",
            resource_id=goal.id,
            project_id=project.id,
            company_id=project.company_id,
            detail={"report_id": report.id, "metric_key": goal.metric_key, "title": goal.title},
        )
    db.commit()
    return [
        ProjectStageGoalRead.model_validate(goal).model_copy(
            update={"suggested_actions": goal_suggested_actions(goal, "unknown")}
        )
        for goal in goals
    ]
