from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TimestampMixin


class WorkspaceMembership(TimestampMixin, Base):
    """A user's explicit boundary inside one GEO workspace."""

    __tablename__ = "geo_workspace_memberships_v1"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "user_id", name="uq_geo_workspace_membership_user_v1"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="viewer", index=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="active", index=True
    )
    invited_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkspaceInvitation(TimestampMixin, Base):
    """A short-lived invite. Only the SHA-256 token digest is persisted."""

    __tablename__ = "geo_workspace_invitations_v1"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="viewer")
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending", index=True
    )
    invited_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LocalAgentEnrollment(TimestampMixin, Base):
    """One-time enrollment token for a Local Agent device."""

    __tablename__ = "geo_local_agent_enrollments_v1"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    requested_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LocalAgentNode(TimestampMixin, Base):
    """Credential-free status record for an agent running on a member computer."""

    __tablename__ = "geo_local_agent_nodes_v1"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    platform: Mapped[str] = mapped_column(String(80), nullable=False)
    agent_version: Mapped[str] = mapped_column(String(40), nullable=False)
    device_token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="active", index=True
    )
    execution_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="status_only"
    )
    capabilities: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    health: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
