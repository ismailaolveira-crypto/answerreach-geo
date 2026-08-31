from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MaturityReport, PlacementRecord, Project, SystemAlert
from app.schemas.search import CrawlTaskCreate
from app.services.auth import utcnow
from app.services.crawl_runner import create_crawl_task
from app.services.job_queue import enqueue_crawl_task_job


def _has_open_placement_alert(
    existing_alerts: list[SystemAlert], *, alert_type: str, placement_id: int
) -> bool:
    return any(
        alert.alert_type == alert_type
        and alert.detail_json.get("placement_id") == placement_id
        and alert.status in {"open", "acknowledged"}
        for alert in existing_alerts
    )


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def create_placement_reminder_alerts(
    db: Session,
    *,
    project_id: int | None = None,
    company_id: int | None = None,
    review_after_days: int = 7,
) -> list[SystemAlert]:
    now = utcnow()
    placement_stmt = select(PlacementRecord, Project).join(Project, Project.id == PlacementRecord.project_id)
    if project_id is not None:
        placement_stmt = placement_stmt.where(PlacementRecord.project_id == project_id)
    if company_id is not None:
        placement_stmt = placement_stmt.where(Project.company_id == company_id)
    rows = list(db.execute(placement_stmt))
    existing_alerts = list(
        db.scalars(
            select(SystemAlert).where(SystemAlert.status.in_(["open", "acknowledged"]))
        )
    )
    alerts: list[SystemAlert] = []

    for placement, project in rows:
        planned_at = _aware(placement.planned_at)
        published_at = _aware(placement.published_at)
        alert_type = None
        severity = "warning"
        title = ""
        message = ""
        due_at = None
        review_task_id = None
        review_job_id = None

        if placement.status == "planned" and planned_at is None:
            alert_type = "placement.unscheduled"
            title = f"投放计划待补充排期：{placement.channel}"
            message = "该投放记录已经进入 planned 状态，但还没有设置 planned_at，建议补充明确排期。"
        elif placement.status == "planned" and planned_at < now:
            alert_type = "placement.overdue"
            severity = "critical"
            due_at = planned_at
            title = f"投放计划已逾期：{placement.channel}"
            message = f"该投放记录计划时间为 {planned_at.isoformat()}，当前仍未发布。"
        elif placement.status == "published" and published_at is not None:
            due_at = published_at + timedelta(days=review_after_days)
            if due_at <= now:
                alert_type = "placement.review_due"
                title = f"投放复盘提醒：{placement.channel}"
                message = "该内容发布已到复盘窗口，建议重新采集目标问题并查看投放前后效果。"

        if alert_type is None or _has_open_placement_alert(
            existing_alerts + alerts, alert_type=alert_type, placement_id=placement.id
        ):
            continue

        if alert_type == "placement.review_due":
            task = create_crawl_task(
                db,
                project,
                CrawlTaskCreate(
                    task_type="placement_review",
                    schedule_type="review",
                    execute_now=False,
                ),
            )
            job = enqueue_crawl_task_job(
                db,
                task=task,
                scheduled_at=now,
            )
            review_task_id = task.id
            review_job_id = job.id

        alert = SystemAlert(
            company_id=project.company_id,
            project_id=project.id,
            alert_type=alert_type,
            severity=severity,
            status="open",
            title=title,
            message=message,
            detail_json={
                "placement_id": placement.id,
                "channel": placement.channel,
                "status": placement.status,
                "planned_at": planned_at.isoformat() if planned_at else None,
                "published_at": published_at.isoformat() if published_at else None,
                "due_at": due_at.isoformat() if due_at else None,
                "review_crawl_task_id": review_task_id,
                "review_queue_job_id": review_job_id,
            },
        )
        db.add(alert)
        db.flush()
        alerts.append(alert)

    return alerts


def _has_open_monitoring_alert(
    existing_alerts: list[SystemAlert], *, alert_type: str, project_id: int, report_id: int
) -> bool:
    return any(
        alert.alert_type == alert_type
        and alert.project_id == project_id
        and int(alert.detail_json.get("target_report_id") or 0) == report_id
        and alert.status in {"open", "acknowledged"}
        for alert in existing_alerts
    )


def create_monitoring_metric_alerts(
    db: Session,
    *,
    project_id: int | None = None,
    company_id: int | None = None,
    score_drop_threshold: int = 10,
    rate_drop_threshold: float = 0.15,
) -> list[SystemAlert]:
    project_stmt = select(Project)
    if project_id is not None:
        project_stmt = project_stmt.where(Project.id == project_id)
    if company_id is not None:
        project_stmt = project_stmt.where(Project.company_id == company_id)
    projects = list(db.scalars(project_stmt))
    existing_alerts = list(
        db.scalars(select(SystemAlert).where(SystemAlert.status.in_(["open", "acknowledged"])))
    )
    alerts: list[SystemAlert] = []

    for project in projects:
        reports = list(
            db.scalars(
                select(MaturityReport)
                .where(MaturityReport.project_id == project.id)
                .order_by(MaturityReport.generated_at.desc().nullslast(), MaturityReport.id.desc())
                .limit(2)
            )
        )
        if len(reports) < 2:
            continue
        latest, previous = reports[0], reports[1]
        latest_metrics = (latest.report_json or {}).get("metrics") or {}
        previous_metrics = (previous.report_json or {}).get("metrics") or {}

        checks = [
            {
                "alert_type": "monitoring.maturity_score_drop",
                "severity": "warning" if previous.total_score - latest.total_score < 20 else "critical",
                "metric_key": "total_score",
                "label": "成熟度分",
                "previous": float(previous.total_score or 0),
                "current": float(latest.total_score or 0),
                "threshold": float(score_drop_threshold),
                "format": "score",
            },
            {
                "alert_type": "monitoring.mention_rate_drop",
                "severity": "warning",
                "metric_key": "mention_rate",
                "label": "企业提及率",
                "previous": float(previous_metrics.get("mention_rate") or 0),
                "current": float(latest_metrics.get("mention_rate") or 0),
                "threshold": float(rate_drop_threshold),
                "format": "rate",
            },
            {
                "alert_type": "monitoring.recommendation_rate_drop",
                "severity": "critical",
                "metric_key": "recommendation_rate",
                "label": "企业推荐率",
                "previous": float(previous_metrics.get("recommendation_rate") or 0),
                "current": float(latest_metrics.get("recommendation_rate") or 0),
                "threshold": float(rate_drop_threshold),
                "format": "rate",
            },
        ]
        for check in checks:
            delta = check["current"] - check["previous"]
            if abs(delta) < check["threshold"] or delta >= 0:
                continue
            if _has_open_monitoring_alert(
                existing_alerts + alerts,
                alert_type=str(check["alert_type"]),
                project_id=project.id,
                report_id=latest.id,
            ):
                continue
            if check["format"] == "rate":
                message = (
                    f"{check['label']}从 {check['previous']:.0%} 下降到 {check['current']:.0%}，"
                    "建议查看最新成熟度报告并生成整改行动项。"
                )
            else:
                message = (
                    f"{check['label']}从 {check['previous']:.0f} 下降到 {check['current']:.0f}，"
                    "建议复核最近采集结果、竞品变化和信源缺口。"
                )
            alert = SystemAlert(
                company_id=project.company_id,
                project_id=project.id,
                alert_type=str(check["alert_type"]),
                severity=str(check["severity"]),
                status="open",
                title=f"监测指标下滑：{project.name} {check['label']}",
                message=message,
                detail_json={
                    "metric_key": check["metric_key"],
                    "previous": check["previous"],
                    "current": check["current"],
                    "delta": delta,
                    "threshold": check["threshold"],
                    "base_report_id": previous.id,
                    "target_report_id": latest.id,
                    "next_action_type": "open_report",
                    "next_action_url": f"/projects/{project.id}/reports/{latest.id}",
                },
            )
            db.add(alert)
            db.flush()
            alerts.append(alert)
    return alerts
