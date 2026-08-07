from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import AuditLog, User
from app.schemas.audit import AuditLogRead

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


@router.get("", response_model=list[AuditLogRead])
def list_audit_logs(
    action: str | None = None,
    project_id: int | None = None,
    company_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin", "company_admin")),
) -> list[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if project_id is not None:
        stmt = stmt.where(AuditLog.project_id == project_id)
    if user.role != "super_admin":
        if user.company_id is None:
            return []
        stmt = stmt.where(AuditLog.company_id == user.company_id)
    elif company_id is not None:
        stmt = stmt.where(AuditLog.company_id == company_id)
    return list(db.scalars(stmt))
