"""add multi-round action measurements and auditable ROI ledger

Revision ID: 20260824_0029
Revises: 20260810_0028
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260824_0029"
down_revision: str | None = "20260810_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _single_action_unique_constraint_name() -> str:
    """Resolve the real name emitted by each database for ``unique=True``.

    SQLite reports the original inline constraint without a name, while PostgreSQL
    creates ``geo_reobservations_v1_action_id_key``.  The batch naming convention
    supplies the fallback name for SQLite.
    """

    inspector = sa.inspect(op.get_bind())
    for constraint in inspector.get_unique_constraints("geo_reobservations_v1"):
        if constraint.get("column_names") == ["action_id"] and constraint.get("name"):
            return str(constraint["name"])
    return "uq_geo_reobservations_v1_action_id"


def upgrade() -> None:
    with op.batch_alter_table("geo_optimization_actions_v1") as batch:
        batch.add_column(
            sa.Column("measurement_plan", sa.JSON(), nullable=False, server_default="{}")
        )

    action_unique_constraint = _single_action_unique_constraint_name()
    with op.batch_alter_table(
        "geo_reobservations_v1",
        naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"},
    ) as batch:
        batch.drop_constraint(action_unique_constraint, type_="unique")
        batch.add_column(sa.Column("round_index", sa.Integer(), nullable=True))
    op.execute("UPDATE geo_reobservations_v1 SET round_index = 1 WHERE round_index IS NULL")
    with op.batch_alter_table(
        "geo_reobservations_v1",
        naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"},
    ) as batch:
        batch.alter_column("round_index", existing_type=sa.Integer(), nullable=False)
        batch.create_unique_constraint(
            "uq_geo_reobservation_action_round_v1", ["action_id", "round_index"]
        )

    op.create_table(
        "geo_business_metric_entries_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("geo_workspaces_v1.id"),
            nullable=False,
        ),
        sa.Column(
            "action_id", sa.Integer(), sa.ForeignKey("geo_optimization_actions_v1.id")
        ),
        sa.Column("metric_type", sa.String(40), nullable=False),
        sa.Column("amount_minor", sa.Integer()),
        sa.Column("quantity", sa.Float()),
        sa.Column("currency", sa.String(3)),
        sa.Column(
            "attribution_type",
            sa.String(24),
            nullable=False,
            server_default="not_applicable",
        ),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_label", sa.String(255), nullable=False),
        sa.Column("source_reference", sa.String(1500)),
        sa.Column("evidence_note", sa.Text(), nullable=False),
        sa.Column(
            "verification_status",
            sa.String(32),
            nullable=False,
            server_default="user_confirmed",
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column(
            "reverses_entry_id",
            sa.Integer(),
            sa.ForeignKey("geo_business_metric_entries_v1.id"),
            unique=True,
        ),
        sa.Column("reversal_reason", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_geo_business_metric_idempotency_v1"
        ),
    )
    for column in (
        "workspace_id",
        "action_id",
        "metric_type",
        "currency",
        "attribution_type",
        "source_type",
        "verification_status",
        "occurred_at",
        "created_by_user_id",
        "reverses_entry_id",
    ):
        op.create_index(
            f"ix_geo_business_metric_entries_v1_{column}",
            "geo_business_metric_entries_v1",
            [column],
        )


def downgrade() -> None:
    op.drop_table("geo_business_metric_entries_v1")
    with op.batch_alter_table(
        "geo_reobservations_v1",
        naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"},
    ) as batch:
        batch.drop_constraint("uq_geo_reobservation_action_round_v1", type_="unique")
        batch.drop_column("round_index")
        batch.create_unique_constraint("uq_geo_reobservations_v1_action_id", ["action_id"])
    with op.batch_alter_table("geo_optimization_actions_v1") as batch:
        batch.drop_column("measurement_plan")
