import secrets
import ipaddress

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.config import get_settings
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
from app.services.auth import (
    canonicalize_email,
    clear_login_failures,
    consume_security_rate_limit,
    DUMMY_PASSWORD_HASH,
    hash_password,
    issue_access_token,
    login_retry_after,
    login_throttle_key,
    password_needs_rehash,
    record_login_failure,
    revoke_session,
    security_rate_limit_retry_after,
    utcnow,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _rate_limit_identity(request: Request) -> str:
    """Use a BFF-forwarded client IP only when the internal shared secret proves it."""

    settings = get_settings()
    expected = settings.internal_proxy_secret
    supplied = request.headers.get("x-geo-proxy-secret")
    claimed = request.headers.get("x-geo-client-ip", "").strip()
    if expected and supplied and secrets.compare_digest(expected, supplied):
        try:
            return str(ipaddress.ip_address(claimed))
        except ValueError:
            pass
    return request.client.host if request.client else "unknown"


@router.post("/register", response_model=UserRead, status_code=201)
def register_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
) -> User:
    """Provision users internally; public signup uses ``/register-tenant``."""
    email = canonicalize_email(str(payload.email))
    existing = db.scalar(select(User).where(func.lower(User.email) == email))
    if existing:
        raise HTTPException(status_code=409, detail="Email already exists")
    existing_user_count = db.scalar(select(User.id).limit(1))
    if existing_user_count is not None and payload.role == "super_admin":
        raise HTTPException(status_code=403, detail="Super admin already initialized")
    user = User(
        company_id=payload.company_id,
        name=payload.name,
        email=email,
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
    payload: TenantRegistrationRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TenantRegistrationResponse:
    """Create a company, first workspace and company admin atomically."""
    settings = get_settings()
    if not settings.public_registration_enabled:
        raise HTTPException(status_code=403, detail="Public registration is disabled")
    client_host = _rate_limit_identity(request)
    retry_after = consume_security_rate_limit(
        db,
        scope="tenant-registration-ip",
        identity=client_host,
        limit=settings.registration_rate_limit_per_hour,
        window=timedelta(hours=1),
    )
    db.commit()
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Too many registration attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )
    email = canonicalize_email(str(payload.email))
    if db.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise HTTPException(status_code=409, detail="Email already exists")
    try:
        company = Company(
            name=payload.company_name.strip(),
            website_url=(
                payload.website_url.strip()
                if payload.website_url and payload.website_url.strip()
                else None
            ),
            brand_aliases=[payload.brand_name.strip()],
            status="active",
        )
        db.add(company)
        db.flush()
        new_user = User(
            company_id=company.id,
            name=payload.name.strip(),
            email=email,
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
        access_token = issue_access_token(db, new_user)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Unable to create account")
    db.refresh(new_user)
    db.refresh(workspace)
    return TenantRegistrationResponse(
        access_token=access_token, user=new_user, workspace_id=workspace.id
    )


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> LoginResponse:
    email = canonicalize_email(str(payload.email))
    client_host = _rate_limit_identity(request)
    settings = get_settings()
    retry_after = security_rate_limit_retry_after(
        db,
        scope="login-ip",
        identity=client_host,
        limit=settings.login_rate_limit_per_15_minutes,
        window=timedelta(minutes=15),
    )
    db.commit()
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )
    throttle_key = login_throttle_key(email, client_host)
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    password_valid = verify_password(
        payload.password,
        user.password_hash if user is not None else DUMMY_PASSWORD_HASH,
    )
    if user is None or not password_valid:
        ip_retry_after = consume_security_rate_limit(
            db,
            scope="login-ip",
            identity=client_host,
            limit=settings.login_rate_limit_per_15_minutes,
            window=timedelta(minutes=15),
        )
        retry_after = login_retry_after(db, throttle_key)
        if retry_after or ip_retry_after:
            db.commit()
            raise HTTPException(
                status_code=429,
                detail="Too many login attempts. Try again later.",
                headers={"Retry-After": str(max(retry_after, ip_retry_after))},
            )
        record_login_failure(db, throttle_key)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="User is inactive")
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
    clear_login_failures(db, throttle_key)
    user.last_login_at = utcnow()
    access_token = issue_access_token(db, user)
    try:
        db.commit()
        db.refresh(user)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=503, detail="Unable to complete login") from None
    return LoginResponse(access_token=access_token, user=user)


@router.get("/me", response_model=UserRead)
def get_me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> None:
    session = getattr(request.state, "auth_session", None)
    if session is not None:
        revoke_session(db, session)
        db.commit()
