from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import MaturityReport, Project, SystemAlert, User
from app.schemas.alert import SystemAlertActionResult, SystemAlertRead, SystemAlertUpdate
from app.services.alert import create_monitoring_metric_alerts, create_placement_reminder_alerts
from app.services.audit import record_audit_log
from app.services.maturity_report import create_report_action_goals

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _scoped_alert_stmt(user: User, status: str | None, project_id: int | None = None):
    stmt = select(SystemAlert).order_by(SystemAlert.created_at.desc())
    if status:
        stmt = stmt.where(SystemAlert.status == status)
    if project_id is not None:
        stmt = stmt.where(SystemAlert.project_id == project_id)
    if user.role != "super_admin":
        if user.company_id is None:
            return stmt.where(SystemAlert.company_id == -1)
        stmt = stmt.where(SystemAlert.company_id == user.company_id)
    return stmt


@router.get("", response_model=list[SystemAlertRead])
def list_alerts(
    status: str | None = "open",
    project_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin", "company_admin")),
) -> list[SystemAlert]:
    if project_id is not None:
        project = db.get(Project, project_id)
        if project is None or (user.role != "super_admin" and project.company_id != user.company_id):
            raise HTTPException(status_code=404, detail="Project not found")
    stmt = _scoped_alert_stmt(user, status, project_id=project_id).limit(limit)
    return list(db.scalars(stmt))


@router.post("/placement-reminders/run", response_model=list[SystemAlertRead], status_code=201)
def run_placement_reminders(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin", "company_admin")),
) -> list[SystemAlert]:
    company_id = None
    if user.role != "super_admin":
        company_id = user.company_id
        if company_id is None:
            raise HTTPException(status_code=403, detail="Company scope required")
    if project_id is not None:
        project = db.get(Project, project_id)
        if project is None or (company_id is not None and project.company_id != company_id):
            raise HTTPException(status_code=404, detail="Project not found")
    alerts = create_placement_reminder_alerts(db, project_id=project_id, company_id=company_id)
    record_audit_log(
        db,
        user=user,
        action="alert.placement_reminders.run",
        resource_type="system_alert",
        project_id=project_id,
        company_id=company_id,
        detail={"created_alert_count": len(alerts)},
    )
    db.commit()
    for alert in alerts:
        db.refresh(alert)
    return alerts


@router.post("/monitoring/run", response_model=list[SystemAlertRead], status_code=201)
def run_monitoring_metric_alerts(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin", "company_admin")),
) -> list[SystemAlert]:
    company_id = None
    if user.role != "super_admin":
        company_id = user.company_id
        if company_id is None:
            raise HTTPException(status_code=403, detail="Company scope required")
    if project_id is not None:
        project = db.get(Project, project_id)
        if project is None or (company_id is not None and project.company_id != company_id):
            raise HTTPException(status_code=404, detail="Project not found")
    alerts = create_monitoring_metric_alerts(db, project_id=project_id, company_id=company_id)
    record_audit_log(
        db,
        user=user,
        action="alert.monitoring.run",
        resource_type="system_alert",
        project_id=project_id,
        company_id=company_id,
        detail={"created_alert_count": len(alerts)},
    )
    db.commit()
    for alert in alerts:
        db.refresh(alert)
    return alerts


@router.patch("/{alert_id}", response_model=SystemAlertRead)
def update_alert(
    alert_id: int,
    payload: SystemAlertUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin", "company_admin")),
) -> SystemAlert:
    if payload.status not in {"open", "acknowledged", "resolved"}:
        raise HTTPException(status_code=422, detail="Unsupported alert status")
    alert = db.get(SystemAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    if user.role != "super_admin" and alert.company_id != user.company_id:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.status = payload.status
    record_audit_log(
        db,
        user=user,
        action="alert.update",
        resource_type="system_alert",
        resource_id=alert.id,
        project_id=alert.project_id,
        company_id=alert.company_id,
        detail={"status": alert.status, "alert_type": alert.alert_type},
    )
    db.commit()
    db.refresh(alert)
    return alert


@router.post("/{alert_id}/actions/create-report-action-goals", response_model=SystemAlertActionResult)
def create_alert_report_action_goals(
    alert_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin", "company_admin")),
) -> SystemAlertActionResult:
    alert = db.get(SystemAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    if user.role != "super_admin" and alert.company_id != user.company_id:
        raise HTTPException(status_code=404, detail="Alert not found")
    if not alert.alert_type.startswith("monitoring."):
        raise HTTPException(status_code=422, detail="Alert does not support report action goals")
    if alert.project_id is None:
        raise HTTPException(status_code=422, detail="Alert is not linked to a project")

    project = db.get(Project, alert.project_id)
    if project is None or (user.role != "super_admin" and project.company_id != user.company_id):
        raise HTTPException(status_code=404, detail="Project not found")
    report_id = int(alert.detail_json.get("target_report_id") or 0)
    report = db.get(MaturityReport, report_id)
    if report is None or report.project_id != project.id:
        raise HTTPException(status_code=404, detail="Maturity report not found")

    goals = create_report_action_goals(db, project, report)
    goal_ids = [goal.id for goal in goals]
    alert_detail = dict(alert.detail_json or {})
    previous_goal_ids = [int(item) for item in alert_detail.get("action_goal_ids") or [] if item]
    combined_goal_ids = list(dict.fromkeys([*previous_goal_ids, *goal_ids]))
    alert_detail.update(
        {
            "last_action_type": "create_report_action_goals",
            "last_action_status": "created" if goal_ids else "already_exists",
            "action_goal_ids": combined_goal_ids,
            "next_action_type": "open_stage_goals",
            "next_action_url": f"/projects/{project.id}#stage-goals",
        }
    )
    alert.detail_json = alert_detail
    if alert.status == "open":
        alert.status = "acknowledged"

    record_audit_log(
        db,
        user=user,
        action="alert.action.create_report_action_goals",
        resource_type="system_alert",
        resource_id=alert.id,
        project_id=project.id,
        company_id=project.company_id,
        detail={
            "alert_type": alert.alert_type,
            "report_id": report.id,
            "created_goal_count": len(goals),
            "goal_ids": goal_ids,
        },
    )
    db.commit()
    db.refresh(alert)
    message = (
        f"已基于报告 #{report.id} 创建 {len(goals)} 个整改阶段目标。"
        if goals
        else f"报告 #{report.id} 的整改阶段目标已存在，未重复创建。"
    )
    return SystemAlertActionResult(
        action_type="create_report_action_goals",
        alert_id=alert.id,
        status="created" if goals else "already_exists",
        message=message,
        resource_type="project_stage_goal",
        resource_ids=combined_goal_ids,
        resource_url=f"/projects/{project.id}#stage-goals",
        detail={
            "project_id": project.id,
            "report_id": report.id,
            "created_goal_count": len(goals),
            "goal_ids": goal_ids,
        },
    )
