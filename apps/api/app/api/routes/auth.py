import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import Company, User
from app.models.cleanroom_v1 import GeoWorkspace
from app.services.workspace_access import add_membership
from app.schemas.user import (
    LoginRequest,
    LoginResponse,
    TenantRegistrationRequest,
    TenantRegistrationResponse,
    UserCreate,
    UserRead,
)
from app.services.auth import create_access_token, hash_password, utcnow, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=201)
def register_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
) -> User:
    """Provision users internally; public signup uses ``/register-tenant``."""
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing:
        raise HTTPException(status_code=409, detail="Email already exists")
    existing_user_count = db.scalar(select(User.id).limit(1))
    if existing_user_count is not None and payload.role == "super_admin":
        raise HTTPException(status_code=403, detail="Super admin already initialized")
    user = User(
        company_id=payload.company_id,
        name=payload.name,
        email=str(payload.email),
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        role=payload.role,
        status=payload.status,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _workspace_slug(db: Session, company_name: str) -> str:
    normalized = "".join(
        char.lower() if char.isascii() and char.isalnum() else "-" for char in company_name
    )
    stem = "-".join(part for part in normalized.split("-") if part)[:48] or "geo-workspace"
    slug = f"{stem}-{secrets.token_hex(5)}"
    while db.scalar(select(GeoWorkspace.id).where(GeoWorkspace.slug == slug)):
        slug = f"{stem}-{secrets.token_hex(5)}"
    return slug


@router.post("/register-tenant", response_model=TenantRegistrationResponse, status_code=201)
def register_tenant(
    payload: TenantRegistrationRequest, db: Session = Depends(get_db)
) -> TenantRegistrationResponse:
    """Create a company, first workspace and company admin atomically."""
    if db.scalar(select(User.id).where(User.email == payload.email)):
        raise HTTPException(status_code=409, detail="Email already exists")
    company = Company(
        name=payload.company_name.strip(),
        website_url=payload.website_url.strip() if payload.website_url and payload.website_url.strip() else None,
        brand_aliases=[payload.brand_name.strip()],
        status="active",
    )
    db.add(company)
    db.flush()
    new_user = User(
        company_id=company.id,
        name=payload.name.strip(),
        email=str(payload.email),
        password_hash=hash_password(payload.password),
        role="company_admin",
        status="active",
    )
    workspace = GeoWorkspace(
        company_id=company.id,
        slug=_workspace_slug(db, company.name),
        brand_name=payload.brand_name.strip(),
        brand_aliases=[payload.brand_name.strip()],
        website_url=company.website_url,
        status="active",
    )
    db.add_all([new_user, workspace])
    db.flush()
    add_membership(
        db,
        workspace_id=workspace.id,
        user_id=new_user.id,
        role="owner",
    )
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Unable to create account")
    db.refresh(new_user)
    db.refresh(workspace)
    return TenantRegistrationResponse(
        access_token=create_access_token(new_user.id), user=new_user, workspace_id=workspace.id
    )


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="User is inactive")
    user.last_login_at = utcnow()
    try:
        db.commit()
        db.refresh(user)
    except SQLAlchemyError:
        db.rollback()
    return LoginResponse(access_token=create_access_token(user.id), user=user)


@router.get("/me", response_model=UserRead)
def get_me(user: User = Depends(get_current_user)) -> User:
    return user
