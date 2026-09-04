from collections.abc import Callable
import re

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Company, Project, User
from app.services.auth import active_session, decode_access_token
from app.services.workspace_access import membership_for, require_workspace_access


WRITE_ROLES = {"super_admin", "company_admin", "content_operator", "reviewer"}
ADMIN_ROLES = {"super_admin"}
CONTENT_ROLES = {"super_admin", "company_admin", "content_operator"}
REVIEW_ROLES = {"super_admin", "company_admin", "reviewer"}
WORKSPACE_PATH = re.compile(r"^/api/v1/workspaces/(\d+)(?:/|$)")
WORKSPACE_ROLE_TO_COMPANY_ROLE = {
    "owner": "company_admin",
    "admin": "company_admin",
    "operator": "content_operator",
    "reviewer": "reviewer",
    "viewer": "viewer",
}


def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization token")
    token = authorization.split(" ", 1)[1]
    claims = decode_access_token(token)
    if claims is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    session = active_session(db, claims)
    if session is None:
        raise HTTPException(status_code=401, detail="Session expired or revoked")
    user = db.get(User, claims.user_id)
    if user is None or user.status != "active":
        raise HTTPException(status_code=401, detail="User not found or inactive")
    if user.credentials_version != claims.credentials_version:
        raise HTTPException(status_code=401, detail="Session expired or revoked")
    request.state.auth_session = session
    match = WORKSPACE_PATH.match(request.url.path)
    if match:
        workspace_id = int(match.group(1))
        require_workspace_access(db, user, workspace_id)
        membership = membership_for(db, workspace_id, user.id)
        if (
            request.method.upper() not in {"GET", "HEAD", "OPTIONS"}
            and user.role != "super_admin"
            and membership is not None
            and membership.role == "viewer"
        ):
            raise HTTPException(status_code=403, detail="Workspace role is read-only")
    return user


def require_roles(*roles: str) -> Callable[[User], User]:
    allowed_roles = set(roles)

    def dependency(
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if user.role in allowed_roles:
            return user
        match = WORKSPACE_PATH.match(request.url.path)
        if match and user.role != "super_admin":
            membership = membership_for(db, int(match.group(1)), user.id)
            effective_role = WORKSPACE_ROLE_TO_COMPANY_ROLE.get(
                membership.role if membership is not None else "",
                "",
            )
            if effective_role in allowed_roles:
                return user
        raise HTTPException(status_code=403, detail="Insufficient role permission")

    return dependency


def can_access_company(user: User, company_id: int) -> bool:
    return user.role == "super_admin" or user.company_id == company_id


def assert_company_access(user: User, company_id: int) -> None:
    if not can_access_company(user, company_id):
        raise HTTPException(status_code=404, detail="Company not found")


def require_project_access(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Project:
    project = get_project_or_404(db, project_id)
    assert_company_access(user, project.company_id)
    return project


def get_company_or_404(db: Session, company_id: int) -> Company:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


def get_project_or_404(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project
