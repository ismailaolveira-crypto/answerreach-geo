"""Add context-linked collaboration center.

Revision ID: 20260827_0035
Revises: 20260824_0034
"""

from alembic import op
import sqlalchemy as sa


revision = "20260827_0035"
down_revision = "20260824_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_collaboration_threads_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("context_type", sa.String(32), nullable=False),
        sa.Column("context_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("workspace_id", "context_type", "context_id", name="uq_geo_collaboration_thread_context_v1"),
    )
    for column in ("workspace_id", "context_type", "context_id", "status", "created_by_user_id", "last_message_at"):
        op.create_index(f"ix_geo_collaboration_threads_v1_{column}", "geo_collaboration_threads_v1", [column])

    op.create_table(
        "geo_collaboration_messages_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("thread_id", sa.Integer(), sa.ForeignKey("geo_collaboration_threads_v1.id"), nullable=False),
        sa.Column("author_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("message_type", sa.String(24), nullable=False, server_default="comment"),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("mention_user_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("attachment_refs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_geo_collaboration_message_idempotency_v1"),
    )
    for column in ("workspace_id", "thread_id", "author_user_id", "message_type"):
        op.create_index(f"ix_geo_collaboration_messages_v1_{column}", "geo_collaboration_messages_v1", [column])

    op.create_table(
        "geo_collaboration_reads_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("thread_id", sa.Integer(), sa.ForeignKey("geo_collaboration_threads_v1.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("last_read_message_id", sa.Integer(), sa.ForeignKey("geo_collaboration_messages_v1.id")),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("thread_id", "user_id", name="uq_geo_collaboration_read_user_v1"),
    )
    for column in ("workspace_id", "thread_id", "user_id", "last_read_message_id"):
        op.create_index(f"ix_geo_collaboration_reads_v1_{column}", "geo_collaboration_reads_v1", [column])

    op.create_table(
        "geo_collaboration_channels_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="disconnected"),
        sa.Column("display_name", sa.String(120)),
        sa.Column("external_tenant_ref", sa.String(255)),
        sa.Column("configured_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("configured_at", sa.DateTime(timezone=True)),
        sa.Column("last_tested_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("workspace_id", "provider", name="uq_geo_collaboration_channel_provider_v1"),
    )
    for column in ("workspace_id", "provider", "status", "configured_by_user_id"):
        op.create_index(f"ix_geo_collaboration_channels_v1_{column}", "geo_collaboration_channels_v1", [column])


def downgrade() -> None:
    op.drop_table("geo_collaboration_channels_v1")
    op.drop_table("geo_collaboration_reads_v1")
    op.drop_table("geo_collaboration_messages_v1")
    op.drop_table("geo_collaboration_threads_v1")
