"""Add office collaboration connectors, member bindings and delivery evidence.

Revision ID: 20260830_0038
Revises: 20260827_0037
"""

from alembic import op
import sqlalchemy as sa


revision = "20260830_0038"
down_revision = "20260827_0037"
branch_labels = None
depends_on = None


def _indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        candidate = f"ix_{table}_{column}"
        if candidate == "ix_geo_collaboration_notification_preferences_v1_updated_by_user_id":
            candidate = "ix_geo_collab_notify_pref_updated_by"
        op.create_index(candidate, table, [column])


def upgrade() -> None:
    channel = "geo_collaboration_channels_v1"
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns(channel)}
    if "connection_mode" not in columns:
        op.add_column(
            channel,
            sa.Column("connection_mode", sa.String(24), nullable=False, server_default="webhook"),
        )
    if "configured_fields" not in columns:
        op.add_column(
            channel,
            sa.Column("configured_fields", sa.JSON(), nullable=False, server_default="[]"),
        )
    if "capabilities" not in columns:
        op.add_column(
            channel,
            sa.Column("capabilities", sa.JSON(), nullable=False, server_default="{}"),
        )
    if "deep_link_base_url" not in columns:
        op.add_column(channel, sa.Column("deep_link_base_url", sa.String(500)))
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes(channel)}
    mode_index = f"ix_{channel}_connection_mode"
    if mode_index not in indexes:
        op.create_index(mode_index, channel, ["connection_mode"])

    op.create_table(
        "geo_collaboration_member_bindings_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("external_user_id", sa.String(255), nullable=False),
        sa.Column("external_id_type", sa.String(32), nullable=False, server_default="user_id"),
        sa.Column("external_display_name", sa.String(255)),
        sa.Column("status", sa.String(24), nullable=False, server_default="verified"),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("verified_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("workspace_id", "user_id", "provider", name="uq_geo_collaboration_member_binding_v1"),
        sa.UniqueConstraint("workspace_id", "provider", "external_user_id", name="uq_geo_collaboration_external_identity_v1"),
    )
    _indexes("geo_collaboration_member_bindings_v1", ("workspace_id", "user_id", "provider", "status", "verified_by_user_id"))

    op.create_table(
        "geo_collaboration_notification_preferences_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider_settings", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("event_types", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_geo_collaboration_notification_preference_v1"),
    )
    _indexes("geo_collaboration_notification_preferences_v1", ("workspace_id", "user_id", "updated_by_user_id"))

    op.create_table(
        "geo_collaboration_deliveries_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("recipient_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("connection_mode", sa.String(24), nullable=False),
        sa.Column("context_type", sa.String(32), nullable=False),
        sa.Column("context_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("message_snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("provider_message_ref", sa.String(255)),
        sa.Column("provider_response", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("error_code", sa.String(120)),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("workspace_id", "idempotency_key", "provider", name="uq_geo_collaboration_delivery_idempotency_v1"),
    )
    _indexes(
        "geo_collaboration_deliveries_v1",
        ("workspace_id", "recipient_user_id", "provider", "context_type", "context_id", "event_type", "status", "requested_by_user_id"),
    )


def downgrade() -> None:
    op.drop_table("geo_collaboration_deliveries_v1")
    op.drop_table("geo_collaboration_notification_preferences_v1")
    op.drop_table("geo_collaboration_member_bindings_v1")
    channel = "geo_collaboration_channels_v1"
    op.drop_index(f"ix_{channel}_connection_mode", table_name=channel)
    for column in ("deep_link_base_url", "capabilities", "configured_fields", "connection_mode"):
        op.drop_column(channel, column)
