"""Add durable deterministic content audits for clean-room GEO V1.

Revision ID: 20260731_0013
Revises: 20260731_0012
"""

from alembic import op
import sqlalchemy as sa


revision = "20260731_0013"
down_revision = "20260731_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_content_audits_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("target_url", sa.String(length=1000)),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("audit_version", sa.String(length=80), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_geo_content_audits_v1_workspace_id", "geo_content_audits_v1", ["workspace_id"])
    op.create_index("ix_geo_content_audits_v1_content_fingerprint", "geo_content_audits_v1", ["content_fingerprint"])


def downgrade() -> None:
    op.drop_table("geo_content_audits_v1")
