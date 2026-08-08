"""Persist account-scoped competitor insight snapshots.

Revision ID: 20260808_0023
Revises: 20260808_0022
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260808_0023"
down_revision = "20260808_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_competitor_insight_snapshots_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("geo_workspaces_v1.id"),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("period_days", sa.Integer(), nullable=False),
        sa.Column("model_key", sa.String(120), nullable=False, server_default=""),
        sa.Column(
            "question_plan_id",
            sa.Integer(),
            sa.ForeignKey("geo_question_plans_v1.id"),
        ),
        sa.Column("evidence_limit", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("scope_fingerprint", sa.String(64), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("source_evidence_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("linked_evidence_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
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
    )
    for column in (
        "workspace_id",
        "created_by_user_id",
        "question_plan_id",
        "scope_fingerprint",
        "input_fingerprint",
        "generated_at",
    ):
        op.create_index(
            f"ix_geo_competitor_insight_snapshots_v1_{column}",
            "geo_competitor_insight_snapshots_v1",
            [column],
        )


def downgrade() -> None:
    op.drop_table("geo_competitor_insight_snapshots_v1")
