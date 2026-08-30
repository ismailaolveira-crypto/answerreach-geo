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

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient role permission")
        return user

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
