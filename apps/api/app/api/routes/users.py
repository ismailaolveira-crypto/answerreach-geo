from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_company_or_404, require_roles
from app.db.session import get_db
from app.models import User
from app.schemas.common import APIMessage
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services.audit import record_audit_log
from app.services.auth import hash_password

router = APIRouter(prefix="/users", tags=["users"])

TENANT_CREATABLE_ROLES = {"content_operator", "reviewer", "viewer"}


def get_user_or_404(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def _assert_user_scope(actor: User, target: User) -> None:
    if actor.role == "super_admin":
        return
    if actor.role == "company_admin" and actor.company_id and actor.company_id == target.company_id:
        return
    raise HTTPException(status_code=404, detail="User not found")


def _normalize_create_payload(actor: User, payload: UserCreate) -> dict:
    data = payload.model_dump()
    if actor.role == "super_admin":
        if data["company_id"] is not None:
            return data
        return data

    if actor.role != "company_admin" or actor.company_id is None:
        raise HTTPException(status_code=403, detail="Insufficient role permission")
    if data["role"] not in TENANT_CREATABLE_ROLES:
        raise HTTPException(status_code=403, detail="Company admin cannot create this role")
    data["company_id"] = actor.company_id
    return data


@router.get("", response_model=list[UserRead])
def list_users(
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("super_admin", "company_admin")),
) -> list[User]:
    stmt = select(User).order_by(User.created_at.desc())
    if actor.role != "super_admin":
        if actor.company_id is None:
            return []
        stmt = stmt.where(User.company_id == actor.company_id)
    return list(db.scalars(stmt))


@router.post("", response_model=UserRead, status_code=201)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("super_admin", "company_admin")),
) -> User:
    data = _normalize_create_payload(actor, payload)
    existing = db.scalar(select(User).where(User.email == data["email"]))
    if existing:
        raise HTTPException(status_code=409, detail="Email already exists")
    if data["company_id"] is not None:
        get_company_or_404(db, data["company_id"])

    user = User(
        company_id=data["company_id"],
        name=data["name"],
        email=str(data["email"]),
        phone=data["phone"],
        password_hash=hash_password(data["password"]),
        role=data["role"],
        status=data["status"],
    )
    db.add(user)
    db.flush()
    record_audit_log(
        db,
        user=actor,
        action="user.create",
        resource_type="user",
        resource_id=user.id,
        company_id=user.company_id,
        detail={"email": user.email, "role": user.role, "status": user.status},
    )
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("super_admin", "company_admin")),
) -> User:
    user = get_user_or_404(db, user_id)
    _assert_user_scope(actor, user)
    update_data = payload.model_dump(exclude_unset=True)

    if actor.role != "super_admin":
        forbidden = {"company_id", "password"} & set(update_data)
        if forbidden:
            raise HTTPException(status_code=403, detail="Company admin cannot update this field")
        if update_data.get("role") and update_data["role"] not in TENANT_CREATABLE_ROLES:
            raise HTTPException(status_code=403, detail="Company admin cannot assign this role")

    if "company_id" in update_data and update_data["company_id"] is not None:
        get_company_or_404(db, update_data["company_id"])
    if "password" in update_data:
        user.password_hash = hash_password(update_data.pop("password"))
    for field, value in update_data.items():
        setattr(user, field, value)

    record_audit_log(
        db,
        user=actor,
        action="user.update",
        resource_type="user",
        resource_id=user.id,
        company_id=user.company_id,
        detail={"updated_fields": list(payload.model_dump(exclude_unset=True).keys())},
    )
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", response_model=APIMessage)
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("super_admin", "company_admin")),
) -> APIMessage:
    user = get_user_or_404(db, user_id)
    _assert_user_scope(actor, user)
    if user.id == actor.id:
        raise HTTPException(status_code=403, detail="Cannot deactivate yourself")
    if actor.role != "super_admin" and user.role not in TENANT_CREATABLE_ROLES:
        raise HTTPException(status_code=403, detail="Company admin cannot deactivate this role")
    user.status = "inactive"
    record_audit_log(
        db,
        user=actor,
        action="user.deactivate",
        resource_type="user",
        resource_id=user.id,
        company_id=user.company_id,
        detail={"email": user.email, "role": user.role},
    )
    db.commit()
    return APIMessage(message="User deactivated")
