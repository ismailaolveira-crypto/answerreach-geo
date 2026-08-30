import hmac
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.cleanroom_v1 import GeoWorkspace
from app.models.user import User
from app.models.workspace_access import (
    LocalAgentEnrollment,
    LocalAgentNode,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from app.schemas.workspace_access import (
    LocalAgentEnrolled,
    LocalAgentEnrollmentCreated,
    LocalAgentEnrollRequest,
    LocalAgentHeartbeat,
    LocalAgentNodeRead,
    WorkspaceInvitationAccept,
    WorkspaceInvitationAcceptResponse,
    WorkspaceInvitationCreate,
    WorkspaceInvitationCreated,
    WorkspaceInvitationPreview,
    WorkspaceInvitationRead,
    WorkspaceMembershipRead,
    WorkspaceMembershipUpdate,
)
from app.services.audit import record_audit_log
from app.services.auth import (
    canonicalize_email,
    hash_password,
    issue_access_token,
    verify_password,
)
from app.services.workspace_access import (
    WORKSPACE_MANAGERS,
    add_membership,
    require_workspace_access,
    require_workspace_manager,
    token_digest,
    utcnow,
)


workspace_router = APIRouter(prefix="/v1", tags=["workspace-access"])
invite_router = APIRouter(prefix="/auth/invitations", tags=["workspace-invitations"])
agent_router = APIRouter(prefix="/v1/local-agent", tags=["local-agent"])

def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _email_hint(email: str) -> str:
    local, _, domain = email.partition("@")
    prefix = local[:2] if len(local) > 2 else local[:1]
    return f"{prefix}{'*' * max(2, len(local) - len(prefix))}@{domain}"


def _membership_read(db: Session, membership: WorkspaceMembership) -> WorkspaceMembershipRead:
    user = db.get(User, membership.user_id)
    if user is None:
        raise HTTPException(status_code=409, detail="Workspace member no longer exists")
    return WorkspaceMembershipRead(
        id=membership.id,
        workspace_id=membership.workspace_id,
        user_id=membership.user_id,
        role=membership.role,
        status=membership.status,
        joined_at=membership.joined_at,
        user=user,
    )


def _node_read(node: LocalAgentNode) -> LocalAgentNodeRead:
    online = node.status == "active" and (utcnow() - _as_utc(node.last_seen_at)) <= timedelta(seconds=45)
    return LocalAgentNodeRead(
        id=node.id,
        workspace_id=node.workspace_id,
        owner_user_id=node.owner_user_id,
        name=node.name,
        hostname=node.hostname,
        platform=node.platform,
        agent_version=node.agent_version,
        status=node.status,
        execution_mode="status_only",
        capabilities=node.capabilities or {},
        health=node.health or {},
        last_seen_at=node.last_seen_at,
        online=online,
        disabled_at=node.disabled_at,
    )


@workspace_router.get(
    "/workspaces/{workspace_id}/members", response_model=list[WorkspaceMembershipRead]
)
def list_workspace_members(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[WorkspaceMembershipRead]:
    require_workspace_access(db, user, workspace_id)
    memberships = list(
        db.scalars(
            select(WorkspaceMembership)
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.status == "active",
            )
            .order_by(WorkspaceMembership.joined_at.asc())
        )
    )
    return [_membership_read(db, membership) for membership in memberships]


@workspace_router.patch(
    "/workspaces/{workspace_id}/members/{membership_id}",
    response_model=WorkspaceMembershipRead,
)
def update_workspace_member(
    workspace_id: int,
    membership_id: int,
    payload: WorkspaceMembershipUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkspaceMembershipRead:
    workspace, actor_membership = require_workspace_manager(db, user, workspace_id)
    membership = db.get(WorkspaceMembership, membership_id)
    if membership is None or membership.workspace_id != workspace_id or membership.status != "active":
        raise HTTPException(status_code=404, detail="Workspace member not found")
    if user.role != "super_admin" and (
        membership.role == "owner" or payload.role == "owner"
    ):
        if actor_membership is None or actor_membership.role != "owner":
            raise HTTPException(status_code=403, detail="Only a workspace owner can change ownership")
    if membership.role == "owner" and payload.role != "owner":
        owner_count = int(
            db.scalar(
                select(func.count())
                .select_from(WorkspaceMembership)
                .where(
                    WorkspaceMembership.workspace_id == workspace_id,
                    WorkspaceMembership.status == "active",
                    WorkspaceMembership.role == "owner",
                )
            )
            or 0
        )
        if owner_count <= 1:
            raise HTTPException(status_code=409, detail="Workspace must keep at least one owner")
    membership.role = payload.role
    record_audit_log(
        db,
        user=user,
        action="workspace.member.role_updated",
        resource_type="workspace_membership",
        resource_id=membership.id,
        company_id=workspace.company_id,
        detail={"workspace_id": workspace_id, "role": payload.role},
    )
    db.commit()
    db.refresh(membership)
    return _membership_read(db, membership)


@workspace_router.delete("/workspaces/{workspace_id}/members/{membership_id}")
def revoke_workspace_member(
    workspace_id: int,
    membership_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    workspace, actor_membership = require_workspace_manager(db, user, workspace_id)
    membership = db.get(WorkspaceMembership, membership_id)
    if membership is None or membership.workspace_id != workspace_id or membership.status != "active":
        raise HTTPException(status_code=404, detail="Workspace member not found")
    if user.role != "super_admin" and membership.role == "owner":
        if actor_membership is None or actor_membership.role != "owner":
            raise HTTPException(status_code=403, detail="Only a workspace owner can revoke an owner")
    if membership.role == "owner":
        owner_count = int(
            db.scalar(
                select(func.count())
                .select_from(WorkspaceMembership)
                .where(
                    WorkspaceMembership.workspace_id == workspace_id,
                    WorkspaceMembership.status == "active",
                    WorkspaceMembership.role == "owner",
                )
            )
            or 0
        )
        if owner_count <= 1:
            raise HTTPException(status_code=409, detail="Workspace must keep at least one owner")
    membership.status = "revoked"
    membership.revoked_at = utcnow()
    record_audit_log(
        db,
        user=user,
        action="workspace.member.revoked",
        resource_type="workspace_membership",
        resource_id=membership.id,
        company_id=workspace.company_id,
        detail={"workspace_id": workspace_id, "user_id": membership.user_id},
    )
    db.commit()
    return {"message": "Workspace access revoked"}


@workspace_router.get(
    "/workspaces/{workspace_id}/invitations", response_model=list[WorkspaceInvitationRead]
)
def list_workspace_invitations(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[WorkspaceInvitation]:
    require_workspace_manager(db, user, workspace_id)
    return list(
        db.scalars(
            select(WorkspaceInvitation)
            .where(WorkspaceInvitation.workspace_id == workspace_id)
            .order_by(WorkspaceInvitation.created_at.desc())
        )
    )


@workspace_router.post(
    "/workspaces/{workspace_id}/invitations",
    response_model=WorkspaceInvitationCreated,
    status_code=201,
)
def create_workspace_invitation(
    workspace_id: int,
    payload: WorkspaceInvitationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkspaceInvitationCreated:
    workspace, _ = require_workspace_manager(db, user, workspace_id)
    if payload.role == "owner":
        raise HTTPException(status_code=422, detail="Ownership must be transferred after joining")
    email = canonicalize_email(str(payload.email))
    token = secrets.token_urlsafe(36)
    now = utcnow()
    for pending in db.scalars(
        select(WorkspaceInvitation).where(
            WorkspaceInvitation.workspace_id == workspace_id,
            WorkspaceInvitation.email == email,
            WorkspaceInvitation.status == "pending",
        )
    ):
        pending.status = "revoked"
        pending.revoked_at = now
    invitation = WorkspaceInvitation(
        workspace_id=workspace_id,
        email=email,
        role=payload.role,
        token_hash=token_digest(token),
        status="pending",
        invited_by_user_id=user.id,
        expires_at=now + timedelta(hours=payload.expires_in_hours),
    )
    db.add(invitation)
    db.flush()
    record_audit_log(
        db,
        user=user,
        action="workspace.invitation.created",
        resource_type="workspace_invitation",
        resource_id=invitation.id,
        company_id=workspace.company_id,
        detail={"workspace_id": workspace_id, "email": email, "role": payload.role},
    )
    db.commit()
    db.refresh(invitation)
    return WorkspaceInvitationCreated(
        **WorkspaceInvitationRead.model_validate(invitation).model_dump(),
        invite_token=token,
        invite_path=f"/invite/{token}",
    )


@workspace_router.delete("/workspaces/{workspace_id}/invitations/{invitation_id}")
def revoke_workspace_invitation(
    workspace_id: int,
    invitation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    workspace, _ = require_workspace_manager(db, user, workspace_id)
    invitation = db.get(WorkspaceInvitation, invitation_id)
    if invitation is None or invitation.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation.status == "pending":
        invitation.status = "revoked"
        invitation.revoked_at = utcnow()
        record_audit_log(
            db,
            user=user,
            action="workspace.invitation.revoked",
            resource_type="workspace_invitation",
            resource_id=invitation.id,
            company_id=workspace.company_id,
            detail={"workspace_id": workspace_id},
        )
        db.commit()
    return {"message": "Invitation revoked"}


def _invitation_from_token(
    db: Session, token: str, *, lock: bool = False
) -> WorkspaceInvitation:
    query = select(WorkspaceInvitation).where(
        WorkspaceInvitation.token_hash == token_digest(token)
    )
    if lock:
        query = query.with_for_update()
    invitation = db.scalar(query)
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation.status != "pending":
        raise HTTPException(status_code=409, detail="Invitation is no longer available")
    if _as_utc(invitation.expires_at) <= utcnow():
        invitation.status = "expired"
        db.commit()
        raise HTTPException(status_code=410, detail="Invitation has expired")
    return invitation


@invite_router.get("/{token}", response_model=WorkspaceInvitationPreview)
def preview_workspace_invitation(token: str, db: Session = Depends(get_db)) -> WorkspaceInvitationPreview:
    invitation = _invitation_from_token(db, token)
    workspace = db.get(GeoWorkspace, invitation.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return WorkspaceInvitationPreview(
        workspace_id=workspace.id,
        workspace_name=workspace.brand_name,
        email_hint=_email_hint(invitation.email),
        role=invitation.role,
        expires_at=invitation.expires_at,
        status=invitation.status,
    )


@invite_router.post("/accept", response_model=WorkspaceInvitationAcceptResponse)
def accept_workspace_invitation(
    payload: WorkspaceInvitationAccept, db: Session = Depends(get_db)
) -> WorkspaceInvitationAcceptResponse:
    invitation = _invitation_from_token(db, payload.token, lock=True)
    workspace = db.get(GeoWorkspace, invitation.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    user = db.scalar(
        select(User).where(func.lower(User.email) == canonicalize_email(invitation.email))
    )
    if user is None:
        # A workspace invitation grants only membership in that workspace.
        # Do not infer company-wide legacy authorization from a scoped invite.
        user = User(
            company_id=None,
            name=payload.name.strip(),
            email=invitation.email,
            password_hash=hash_password(payload.password),
            role="viewer",
            status="active",
        )
        db.add(user)
        db.flush()
    else:
        if user.company_id is not None and user.company_id != workspace.company_id:
            raise HTTPException(status_code=409, detail="Account belongs to another organization")
        if not verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid account password")
        if user.status != "active":
            raise HTTPException(status_code=403, detail="User is inactive")
    add_membership(
        db,
        workspace_id=workspace.id,
        user_id=user.id,
        role=invitation.role,
        invited_by_user_id=invitation.invited_by_user_id,
    )
    invitation.status = "accepted"
    invitation.accepted_by_user_id = user.id
    invitation.accepted_at = utcnow()
    record_audit_log(
        db,
        user=user,
        action="workspace.invitation.accepted",
        resource_type="workspace_invitation",
        resource_id=invitation.id,
        company_id=workspace.company_id,
        detail={"workspace_id": workspace.id, "role": invitation.role},
    )
    access_token = issue_access_token(db, user)
    db.commit()
    db.refresh(user)
    return WorkspaceInvitationAcceptResponse(
        access_token=access_token, user=user, workspace_id=workspace.id
    )


@workspace_router.post(
    "/workspaces/{workspace_id}/local-agent-enrollments",
    response_model=LocalAgentEnrollmentCreated,
    status_code=201,
)
def create_local_agent_enrollment(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LocalAgentEnrollmentCreated:
    require_workspace_access(db, user, workspace_id)
    token = secrets.token_urlsafe(36)
    expires_at = utcnow() + timedelta(minutes=20)
    db.add(
        LocalAgentEnrollment(
            workspace_id=workspace_id,
            requested_by_user_id=user.id,
            token_hash=token_digest(token),
            expires_at=expires_at,
        )
    )
    db.commit()
    return LocalAgentEnrollmentCreated(
        workspace_id=workspace_id,
        enrollment_token=token,
        expires_at=expires_at,
        command_hint=(
            "python apps/api/scripts/run_local_agent.py enroll "
            f"--server http://HOST:3000 --token {token}"
        ),
    )


@workspace_router.get(
    "/workspaces/{workspace_id}/local-agent-nodes", response_model=list[LocalAgentNodeRead]
)
def list_local_agent_nodes(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[LocalAgentNodeRead]:
    require_workspace_access(db, user, workspace_id)
    nodes = list(
        db.scalars(
            select(LocalAgentNode)
            .where(LocalAgentNode.workspace_id == workspace_id)
            .order_by(LocalAgentNode.last_seen_at.desc())
        )
    )
    return [_node_read(node) for node in nodes]


@workspace_router.delete("/workspaces/{workspace_id}/local-agent-nodes/{node_id}")
def disable_local_agent_node(
    workspace_id: int,
    node_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    workspace, membership = require_workspace_access(db, user, workspace_id)
    node = db.get(LocalAgentNode, node_id)
    if node is None or node.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Local Agent not found")
    is_manager = user.role == "super_admin" or (
        membership is not None and membership.role in WORKSPACE_MANAGERS
    )
    if node.owner_user_id != user.id and not is_manager:
        raise HTTPException(status_code=403, detail="Cannot disable another member's Local Agent")
    node.status = "disabled"
    node.disabled_at = utcnow()
    record_audit_log(
        db,
        user=user,
        action="local_agent.disabled",
        resource_type="local_agent_node",
        resource_id=node.id,
        company_id=workspace.company_id,
        detail={"workspace_id": workspace_id},
    )
    db.commit()
    return {"message": "Local Agent disabled"}


@agent_router.post("/enroll", response_model=LocalAgentEnrolled, status_code=201)
def enroll_local_agent(
    payload: LocalAgentEnrollRequest, db: Session = Depends(get_db)
) -> LocalAgentEnrolled:
    enrollment = db.scalar(
        select(LocalAgentEnrollment)
        .where(LocalAgentEnrollment.token_hash == token_digest(payload.enrollment_token))
        .with_for_update()
    )
    if enrollment is None:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    if enrollment.used_at is not None:
        raise HTTPException(status_code=409, detail="Enrollment was already used")
    if _as_utc(enrollment.expires_at) <= utcnow():
        raise HTTPException(status_code=410, detail="Enrollment has expired")
    device_token = secrets.token_urlsafe(48)
    now = utcnow()
    node = LocalAgentNode(
        workspace_id=enrollment.workspace_id,
        owner_user_id=enrollment.requested_by_user_id,
        name=payload.name,
        hostname=payload.hostname,
        platform=payload.platform,
        agent_version=payload.agent_version,
        device_token_hash=token_digest(device_token),
        status="active",
        execution_mode="status_only",
        capabilities=payload.capabilities,
        health=payload.health,
        last_seen_at=now,
    )
    enrollment.used_at = now
    db.add(node)
    db.commit()
    db.refresh(node)
    return LocalAgentEnrolled(**_node_read(node).model_dump(), device_token=device_token)


@agent_router.post("/nodes/{node_id}/heartbeat", response_model=LocalAgentNodeRead)
def heartbeat_local_agent(
    node_id: int,
    payload: LocalAgentHeartbeat,
    x_geo_agent_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> LocalAgentNodeRead:
    node = db.get(LocalAgentNode, node_id)
    if node is None or node.status != "active":
        raise HTTPException(status_code=404, detail="Local Agent not found")
    supplied_hash = token_digest(x_geo_agent_token or "")
    if not x_geo_agent_token or not hmac.compare_digest(node.device_token_hash, supplied_hash):
        raise HTTPException(status_code=401, detail="Invalid Local Agent token")
    node.agent_version = payload.agent_version
    node.capabilities = payload.capabilities
    node.health = payload.health
    node.last_seen_at = utcnow()
    db.commit()
    db.refresh(node)
    return _node_read(node)
