"""Add private collaboration attachments.

Revision ID: 20260827_0036
Revises: 20260827_0035
"""

from alembic import op
import sqlalchemy as sa


revision = "20260827_0036"
down_revision = "20260827_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_collaboration_attachments_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("uploader_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("geo_collaboration_messages_v1.id")),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(180), nullable=False, unique=True),
        sa.Column("mime_type", sa.String(160), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("media_kind", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="available"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    for column in ("workspace_id", "uploader_user_id", "message_id", "sha256", "media_kind", "status"):
        op.create_index(f"ix_geo_collaboration_attachments_v1_{column}", "geo_collaboration_attachments_v1", [column])


def downgrade() -> None:
    op.drop_table("geo_collaboration_attachments_v1")
