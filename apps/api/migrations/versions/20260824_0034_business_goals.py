"""Add auditable GEO business goals.

Revision ID: 20260824_0034
Revises: 20260824_0033
"""

from alembic import op
import sqlalchemy as sa


revision = "20260824_0034"
down_revision = "20260824_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_business_goals_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("metric_key", sa.String(64), nullable=False, server_default="shortlist_rate"),
        sa.Column("baseline_value", sa.Float()),
        sa.Column("target_value", sa.Float(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("question_plan_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("model_keys", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("action_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("scope_snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_geo_business_goals_v1_workspace_id", "geo_business_goals_v1", ["workspace_id"])
    op.create_index("ix_geo_business_goals_v1_metric_key", "geo_business_goals_v1", ["metric_key"])
    op.create_index("ix_geo_business_goals_v1_owner_user_id", "geo_business_goals_v1", ["owner_user_id"])
    op.create_index("ix_geo_business_goals_v1_status", "geo_business_goals_v1", ["status"])
    op.create_index("ix_geo_business_goals_v1_created_by_user_id", "geo_business_goals_v1", ["created_by_user_id"])


def downgrade() -> None:
    op.drop_table("geo_business_goals_v1")
