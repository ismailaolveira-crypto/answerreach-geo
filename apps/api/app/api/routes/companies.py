from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    WRITE_ROLES,
    assert_company_access,
    get_company_or_404,
    get_current_user,
    require_roles,
)
from app.db.session import get_db
from app.models import Company, User
from app.schemas.common import APIMessage
from app.schemas.company import CompanyCreate, CompanyRead, CompanyUpdate

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=list[CompanyRead])
def list_companies(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[Company]:
    stmt = select(Company).order_by(Company.created_at.desc())
    if user.role != "super_admin":
        if user.company_id is None:
            return []
        stmt = stmt.where(Company.id == user.company_id)
    return list(db.scalars(stmt))


@router.post("", response_model=CompanyRead, status_code=201)
def create_company(
    payload: CompanyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> Company:
    if user.role != "super_admin" and user.company_id is not None:
        raise HTTPException(status_code=403, detail="Company user cannot create another company")
    company = Company(**payload.model_dump())
    db.add(company)
    db.flush()
    if user.role != "super_admin" and user.company_id is None:
        user.company_id = company.id
    db.commit()
    db.refresh(company)
    return company


@router.get("/{company_id}", response_model=CompanyRead)
def get_company(
    company_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Company:
    company = get_company_or_404(db, company_id)
    assert_company_access(user, company.id)
    return company


@router.patch("/{company_id}", response_model=CompanyRead)
def update_company(
    company_id: int,
    payload: CompanyUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> Company:
    company = get_company_or_404(db, company_id)
    assert_company_access(user, company.id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(company, field, value)
    db.commit()
    db.refresh(company)
    return company


@router.delete("/{company_id}", response_model=APIMessage)
def delete_company(
    company_id: int,
    db: Session = Depends(get_db),
    _user: object = Depends(require_roles("super_admin")),
) -> APIMessage:
    company = get_company_or_404(db, company_id)
    db.delete(company)
    db.commit()
    return APIMessage(message="Company deleted")
