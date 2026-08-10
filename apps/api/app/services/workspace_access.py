from datetime import UTC, datetime
from hashlib import sha256

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.cleanroom_v1 import GeoWorkspace
from app.models.user import User
from app.models.workspace_access import WorkspaceMembership


WORKSPACE_ROLES = {"owner", "admin", "operator", "reviewer", "viewer"}
WORKSPACE_MANAGERS = {"owner", "admin"}
WORKSPACE_MUTATORS = {"owner", "admin", "operator", "reviewer"}


def utcnow() -> datetime:
    return datetime.now(UTC)


def token_digest(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def membership_for(
    db: Session, workspace_id: int, user_id: int
) -> WorkspaceMembership | None:
    return db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.status == "active",
        )
    )


def workspace_has_memberships(db: Session, workspace_id: int) -> bool:
    return bool(
        db.scalar(
            select(func.count())
            .select_from(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == workspace_id)
        )
    )


def can_access_workspace(db: Session, user: User, workspace: GeoWorkspace) -> bool:
    if user.role == "super_admin":
        return True
    return membership_for(db, workspace.id, user.id) is not None


def require_workspace_access(
    db: Session, user: User, workspace_id: int
) -> tuple[GeoWorkspace, WorkspaceMembership | None]:
    workspace = db.get(GeoWorkspace, workspace_id)
    if workspace is None or not can_access_workspace(db, user, workspace):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace, membership_for(db, workspace_id, user.id)


def require_workspace_manager(
    db: Session, user: User, workspace_id: int
) -> tuple[GeoWorkspace, WorkspaceMembership | None]:
    workspace, membership = require_workspace_access(db, user, workspace_id)
    if user.role == "super_admin":
        return workspace, membership
    if membership is None or membership.role not in WORKSPACE_MANAGERS:
        raise HTTPException(status_code=403, detail="Workspace admin permission required")
    return workspace, membership


def add_membership(
    db: Session,
    *,
    workspace_id: int,
    user_id: int,
    role: str,
    invited_by_user_id: int | None = None,
) -> WorkspaceMembership:
    if role not in WORKSPACE_ROLES:
        raise ValueError(f"Unsupported workspace role: {role}")
    membership = db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
    )
    now = utcnow()
    if membership is None:
        membership = WorkspaceMembership(
            workspace_id=workspace_id,
            user_id=user_id,
            role=role,
            status="active",
            invited_by_user_id=invited_by_user_id,
            joined_at=now,
        )
        db.add(membership)
    else:
        membership.role = role
        membership.status = "active"
        membership.invited_by_user_id = invited_by_user_id or membership.invited_by_user_id
        membership.joined_at = now
        membership.revoked_at = None
    db.flush()
    return membership


def backfill_legacy_workspace_memberships(db: Session) -> int:
    """Make old company-wide access explicit without granting future users access."""

    workspaces = list(db.scalars(select(GeoWorkspace)))
    created = 0
    role_map = {
        "company_admin": "owner",
        "content_operator": "operator",
        "reviewer": "reviewer",
        "viewer": "viewer",
    }
    for workspace in workspaces:
        if workspace_has_memberships(db, workspace.id):
            continue
        users = list(
            db.scalars(
                select(User).where(
                    User.company_id == workspace.company_id, User.status == "active"
                )
            )
        )
        for user in users:
            add_membership(
                db,
                workspace_id=workspace.id,
                user_id=user.id,
                role=role_map.get(user.role, "viewer"),
            )
            created += 1
    if created:
        db.commit()
    return created
