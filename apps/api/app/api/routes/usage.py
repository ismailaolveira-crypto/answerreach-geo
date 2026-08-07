from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_project_or_404, require_roles
from app.db.session import get_db
from app.models import LLMProvider, UsageRecord, User
from app.schemas.usage import UsageRecordRead, UsageSummary

router = APIRouter(prefix="/usage", tags=["usage"])


def _scoped_usage_stmt(user: User, company_id: int | None, project_id: int | None):
    stmt = select(UsageRecord)
    if user.role != "super_admin":
        if user.company_id is None:
            return stmt.where(UsageRecord.company_id == -1)
        stmt = stmt.where(UsageRecord.company_id == user.company_id)
    elif company_id is not None:
        stmt = stmt.where(UsageRecord.company_id == company_id)
    if project_id is not None:
        stmt = stmt.where(UsageRecord.project_id == project_id)
    return stmt


@router.get("/records", response_model=list[UsageRecordRead])
def list_usage_records(
    company_id: int | None = None,
    project_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin", "company_admin")),
) -> list[UsageRecord]:
    if project_id is not None:
        project = get_project_or_404(db, project_id)
        if user.role != "super_admin" and project.company_id != user.company_id:
            return []
    stmt = _scoped_usage_stmt(user, company_id, project_id)
    return list(db.scalars(stmt.order_by(UsageRecord.created_at.desc()).limit(limit)))


@router.get("/summary", response_model=UsageSummary)
def get_usage_summary(
    company_id: int | None = None,
    project_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin", "company_admin")),
) -> UsageSummary:
    if project_id is not None:
        project = get_project_or_404(db, project_id)
        if user.role != "super_admin" and project.company_id != user.company_id:
            return UsageSummary(
                company_id=user.company_id,
                project_id=project_id,
                total_records=0,
                total_prompt_tokens=0,
                total_completion_tokens=0,
                total_tokens=0,
                total_estimated_cost=0,
                currency="USD",
                by_action=[],
                by_provider=[],
            )

    scoped_subquery = _scoped_usage_stmt(user, company_id, project_id).subquery()
    totals = db.execute(
        select(
            func.count(scoped_subquery.c.id),
            func.coalesce(func.sum(scoped_subquery.c.prompt_tokens), 0),
            func.coalesce(func.sum(scoped_subquery.c.completion_tokens), 0),
            func.coalesce(func.sum(scoped_subquery.c.total_tokens), 0),
            func.coalesce(func.sum(scoped_subquery.c.estimated_cost), 0),
        )
    ).one()
    by_action_rows = db.execute(
        select(
            scoped_subquery.c.action,
            func.count(scoped_subquery.c.id),
            func.coalesce(func.sum(scoped_subquery.c.total_tokens), 0),
            func.coalesce(func.sum(scoped_subquery.c.estimated_cost), 0),
        )
        .group_by(scoped_subquery.c.action)
        .order_by(func.coalesce(func.sum(scoped_subquery.c.total_tokens), 0).desc())
    ).all()
    by_provider_rows = db.execute(
        select(
            scoped_subquery.c.provider_id,
            LLMProvider.name,
            func.count(scoped_subquery.c.id),
            func.coalesce(func.sum(scoped_subquery.c.total_tokens), 0),
            func.coalesce(func.sum(scoped_subquery.c.estimated_cost), 0),
        )
        .outerjoin(LLMProvider, LLMProvider.id == scoped_subquery.c.provider_id)
        .group_by(scoped_subquery.c.provider_id, LLMProvider.name)
        .order_by(func.coalesce(func.sum(scoped_subquery.c.total_tokens), 0).desc())
    ).all()

    scoped_company_id = user.company_id if user.role != "super_admin" else company_id
    return UsageSummary(
        company_id=scoped_company_id,
        project_id=project_id,
        total_records=int(totals[0] or 0),
        total_prompt_tokens=int(totals[1] or 0),
        total_completion_tokens=int(totals[2] or 0),
        total_tokens=int(totals[3] or 0),
        total_estimated_cost=round(float(totals[4] or 0), 6),
        currency="USD",
        by_action=[
            {
                "action": row[0],
                "records": int(row[1] or 0),
                "total_tokens": int(row[2] or 0),
                "estimated_cost": round(float(row[3] or 0), 6),
            }
            for row in by_action_rows
        ],
        by_provider=[
            {
                "provider_id": row[0],
                "provider_name": row[1] or "unknown",
                "records": int(row[2] or 0),
                "total_tokens": int(row[3] or 0),
                "estimated_cost": round(float(row[4] or 0), 6),
            }
            for row in by_provider_rows
        ],
    )
