from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def record_audit_log(
    db: Session,
    *,
    user: User | None,
    action: str,
    resource_type: str,
    resource_id: int | None = None,
    project_id: int | None = None,
    company_id: int | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    log = AuditLog(
        actor_user_id=user.id if user else None,
        actor_role=user.role if user else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        project_id=project_id,
        company_id=company_id,
        detail_json=detail or {},
    )
    db.add(log)
    db.flush()
    return log
