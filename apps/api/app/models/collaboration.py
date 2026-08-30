from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TimestampMixin


class GeoCollaborationThread(TimestampMixin, Base):
    """A durable discussion anchored to one real workspace object."""

    __tablename__ = "geo_collaboration_threads_v1"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "context_type",
            "context_id",
            name="uq_geo_collaboration_thread_context_v1",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    context_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    context_id: Mapped[int] = mapped_column(nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", index=True)
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    assignee_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), index=True
    )
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    participant_user_ids: Mapped[list[int]] = mapped_column(
        JSON, nullable=False, default=list
    )
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )


class GeoCollaborationMessage(TimestampMixin, Base):
    """A user comment or an immutable system activity in a context thread."""

    __tablename__ = "geo_collaboration_messages_v1"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_geo_collaboration_message_idempotency_v1",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("geo_collaboration_threads_v1.id"), nullable=False, index=True
    )
    author_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), index=True
    )
    message_type: Mapped[str] = mapped_column(
        String(24), nullable=False, default="comment", index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    mention_user_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    attachment_refs: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)


class GeoCollaborationMention(TimestampMixin, Base):
    """Normalized mention index used for bounded collaboration summaries."""

    __tablename__ = "geo_collaboration_mentions_v1"
    __table_args__ = (
        UniqueConstraint(
            "message_id", "user_id", name="uq_geo_collaboration_mention_message_user_v1"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("geo_collaboration_threads_v1.id"), nullable=False, index=True
    )
    message_id: Mapped[int] = mapped_column(
        ForeignKey("geo_collaboration_messages_v1.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)


class GeoCollaborationAttachment(TimestampMixin, Base):
    """A private workspace file that may be attached to exactly one message."""

    __tablename__ = "geo_collaboration_attachments_v1"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    uploader_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("geo_collaboration_messages_v1.id"), index=True
    )
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(String(160), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    media_kind: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="available", index=True
    )


class GeoCollaborationRead(TimestampMixin, Base):
    __tablename__ = "geo_collaboration_reads_v1"
    __table_args__ = (
        UniqueConstraint(
            "thread_id", "user_id", name="uq_geo_collaboration_read_user_v1"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("geo_collaboration_threads_v1.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    last_read_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("geo_collaboration_messages_v1.id"), index=True
    )
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GeoCollaborationChannel(TimestampMixin, Base):
    """Non-secret channel state. Credentials remain in encrypted workspace secrets."""

    __tablename__ = "geo_collaboration_channels_v1"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "provider", name="uq_geo_collaboration_channel_provider_v1"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="disconnected", index=True
    )
    display_name: Mapped[str | None] = mapped_column(String(120))
    external_tenant_ref: Mapped[str | None] = mapped_column(String(255))
    configured_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), index=True
    )
    configured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    connection_mode: Mapped[str] = mapped_column(
        String(24), nullable=False, default="webhook", index=True
    )
    configured_fields: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    capabilities: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    deep_link_base_url: Mapped[str | None] = mapped_column(String(500))


class GeoCollaborationMemberBinding(TimestampMixin, Base):
    """A verified mapping between a GEO member and one provider identity."""

    __tablename__ = "geo_collaboration_member_bindings_v1"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "user_id",
            "provider",
            name="uq_geo_collaboration_member_binding_v1",
        ),
        UniqueConstraint(
            "workspace_id",
            "provider",
            "external_user_id",
            name="uq_geo_collaboration_external_identity_v1",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    external_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_id_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="user_id"
    )
    external_display_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="verified", index=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), index=True
    )


class GeoCollaborationNotificationPreference(TimestampMixin, Base):
    """Per-member notification routing; provider defaults are deliberately explicit."""

    __tablename__ = "geo_collaboration_notification_preferences_v1"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "user_id",
            name="uq_geo_collaboration_notification_preference_v1",
        ),
        Index("ix_geo_collab_notify_pref_updated_by", "updated_by_user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    provider_settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    event_types: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id")
    )


class GeoCollaborationDelivery(TimestampMixin, Base):
    """Immutable evidence for one explicit external notification attempt."""

    __tablename__ = "geo_collaboration_deliveries_v1"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            "provider",
            name="uq_geo_collaboration_delivery_idempotency_v1",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    recipient_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    connection_mode: Mapped[str] = mapped_column(String(24), nullable=False)
    context_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    context_id: Mapped[int] = mapped_column(nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    message_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    provider_message_ref: Mapped[str | None] = mapped_column(String(255))
    provider_response: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    requested_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
