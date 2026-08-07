"""Add credential-free DeepSeek browser account pool.

Revision ID: 20260801_0014
Revises: 20260731_0013
"""

from alembic import op
import sqlalchemy as sa


revision = "20260801_0014"
down_revision = "20260731_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_browser_accounts_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("provider_key", sa.String(length=40), nullable=False),
        sa.Column("alias", sa.String(length=80), nullable=False),
        sa.Column("ego_task_space_id", sa.Integer(), nullable=False),
        sa.Column("cohort", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("health_note", sa.String(length=500)),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("cooldown_until", sa.DateTime(timezone=True)),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("lease_token_hash", sa.String(length=64)),
        sa.Column("lease_worker_id", sa.String(length=120)),
        sa.Column("lease_run_id", sa.Integer(), sa.ForeignKey("geo_observation_runs_v1.id")),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("workspace_id", "provider_key", "alias", name="uq_geo_browser_account_alias_v1"),
        sa.UniqueConstraint("provider_key", "ego_task_space_id", name="uq_geo_browser_account_task_space_v1"),
    )
    op.create_index("ix_geo_browser_accounts_v1_workspace_id", "geo_browser_accounts_v1", ["workspace_id"])
    op.create_index("ix_geo_browser_accounts_v1_provider_key", "geo_browser_accounts_v1", ["provider_key"])
    op.create_index("ix_geo_browser_accounts_v1_status", "geo_browser_accounts_v1", ["status"])


def downgrade() -> None:
    op.drop_table("geo_browser_accounts_v1")
