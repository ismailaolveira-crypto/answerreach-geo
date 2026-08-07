from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import ReportTemplate, User
from app.schemas.report import ReportTemplateCreate, ReportTemplateRead, ReportTemplateUpdate
from app.services.audit import record_audit_log
from app.services.report_templates import seed_default_report_template

router = APIRouter(prefix="/report-templates", tags=["report-templates"])


def get_report_template_or_404(db: Session, template_id: int) -> ReportTemplate:
    template = db.get(ReportTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Report template not found")
    return template


@router.get("", response_model=list[ReportTemplateRead])
def list_report_templates(
    status: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles("super_admin", "company_admin", "reviewer")),
) -> list[ReportTemplate]:
    seed_default_report_template(db)
    stmt = select(ReportTemplate).order_by(ReportTemplate.status.asc(), ReportTemplate.id.asc())
    if status is not None:
        stmt = stmt.where(ReportTemplate.status == status)
    return list(db.scalars(stmt))


@router.post("", response_model=ReportTemplateRead, status_code=201)
def create_report_template(
    payload: ReportTemplateCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
) -> ReportTemplate:
    template = ReportTemplate(**payload.model_dump())
    db.add(template)
    db.flush()
    record_audit_log(
        db,
        user=user,
        action="report_template.create",
        resource_type="report_template",
        resource_id=template.id,
        detail={
            "template_key": template.template_key,
            "name": template.name,
            "version": template.version,
        },
    )
    db.commit()
    db.refresh(template)
    return template


@router.patch("/{template_id}", response_model=ReportTemplateRead)
def update_report_template(
    template_id: int,
    payload: ReportTemplateUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
) -> ReportTemplate:
    template = get_report_template_or_404(db, template_id)
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(template, field, value)
    if update_data and "version" not in update_data:
        template.version += 1
    record_audit_log(
        db,
        user=user,
        action="report_template.update",
        resource_type="report_template",
        resource_id=template.id,
        detail={"updated_fields": list(update_data.keys()), "version": template.version},
    )
    db.commit()
    db.refresh(template)
    return template
