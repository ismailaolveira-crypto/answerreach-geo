"""Add encrypted workspace integration secret references.

Revision ID: 20260807_0019
Revises: 20260807_0018
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260807_0019"
down_revision = "20260807_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_workspace_secrets_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("secret_key", sa.String(length=80), nullable=False),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("workspace_id", "secret_key", name="uq_geo_workspace_secret_key_v1"),
    )
    op.create_index("ix_geo_workspace_secrets_v1_workspace_id", "geo_workspace_secrets_v1", ["workspace_id"])
    op.create_index("ix_geo_workspace_secrets_v1_secret_key", "geo_workspace_secrets_v1", ["secret_key"])
    op.create_index("ix_geo_workspace_secrets_v1_updated_by_user_id", "geo_workspace_secrets_v1", ["updated_by_user_id"])


def downgrade() -> None:
    op.drop_index("ix_geo_workspace_secrets_v1_updated_by_user_id", table_name="geo_workspace_secrets_v1")
    op.drop_index("ix_geo_workspace_secrets_v1_secret_key", table_name="geo_workspace_secrets_v1")
    op.drop_index("ix_geo_workspace_secrets_v1_workspace_id", table_name="geo_workspace_secrets_v1")
    op.drop_table("geo_workspace_secrets_v1")
