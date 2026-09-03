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
    bind = op.get_bind()
    duplicates = bind.execute(
        sa.text(
            f"""
            SELECT workspace_id, action_id, COUNT(*) AS active_count
            FROM geo_agent_runs_v1
            WHERE {ACTIVE_RUN_PREDICATE}
            GROUP BY workspace_id, action_id
            HAVING COUNT(*) > 1
            LIMIT 10
            """
        )
    ).fetchall()
    if duplicates:
        sample = ", ".join(
            f"workspace_id={row[0]} action_id={row[1]} count={row[2]}" for row in duplicates
        )
        raise RuntimeError(
            "Cannot create uq_geo_agent_run_active_action_v1: duplicate active Agent runs exist; "
            f"resolve them before retrying the migration ({sample})"
        )
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
