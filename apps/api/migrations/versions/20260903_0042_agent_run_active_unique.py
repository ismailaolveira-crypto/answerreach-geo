"""Enforce one active Agent run per action.

Revision ID: 20260903_0042
Revises: 20260830_0041
"""

from alembic import op
import sqlalchemy as sa


revision = "20260903_0042"
down_revision = "20260830_0041"
branch_labels = None
depends_on = None


ACTIVE_RUN_PREDICATE = "status IN ('queued', 'resuming', 'running', 'cancelling')"


def upgrade() -> None:
    op.create_index(
        "uq_geo_agent_run_active_action_v1",
        "geo_agent_runs_v1",
        ["workspace_id", "action_id"],
        unique=True,
        sqlite_where=sa.text(ACTIVE_RUN_PREDICATE),
        postgresql_where=sa.text(ACTIVE_RUN_PREDICATE),
    )


def downgrade() -> None:
    op.drop_index("uq_geo_agent_run_active_action_v1", table_name="geo_agent_runs_v1")
