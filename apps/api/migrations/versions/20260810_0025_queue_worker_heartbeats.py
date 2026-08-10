"""add durable queue worker heartbeats

Revision ID: 20260810_0025
Revises: 20260809_0024
Create Date: 2026-08-10
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260810_0025"
down_revision: str | None = "20260809_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if _table_exists("queue_worker_heartbeats"):
        return
    op.create_table(
        "queue_worker_heartbeats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("worker_id", sa.String(length=180), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("concurrency", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id")),
        sa.Column(
            "observation_batch_id",
            sa.Integer(),
            sa.ForeignKey("geo_observation_batches_v1.id"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint("worker_id", name="uq_queue_worker_heartbeat_worker_id"),
    )
    for column in (
        "id",
        "worker_id",
        "status",
        "workspace_id",
        "observation_batch_id",
        "last_seen_at",
    ):
        op.create_index(
            f"ix_queue_worker_heartbeats_{column}",
            "queue_worker_heartbeats",
            [column],
        )


def downgrade() -> None:
    if _table_exists("queue_worker_heartbeats"):
        op.drop_table("queue_worker_heartbeats")
