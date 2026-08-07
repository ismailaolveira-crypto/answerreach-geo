"""Add human publication receipts and comparable action retests.

Revision ID: 20260808_0021
Revises: 20260808_0020
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260808_0021"
down_revision = "20260808_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("geo_distribution_targets_v1") as batch:
        batch.add_column(
            sa.Column(
                "human_publish_status",
                sa.String(32),
                nullable=False,
                server_default="not_ready",
            )
        )
        batch.add_column(sa.Column("public_url", sa.String(1500)))
        batch.add_column(
            sa.Column(
                "publication_verification_status",
                sa.String(32),
                nullable=False,
                server_default="not_checked",
            )
        )
        batch.add_column(sa.Column("published_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("published_by_user_id", sa.Integer()))
        batch.create_foreign_key(
            "fk_geo_distribution_target_published_by_v1",
            "users",
            ["published_by_user_id"],
            ["id"],
        )
        batch.create_index(
            "ix_geo_distribution_targets_v1_human_publish_status",
            ["human_publish_status"],
        )
        batch.create_index(
            "ix_geo_distribution_targets_v1_published_by_user_id",
            ["published_by_user_id"],
        )

    op.execute(
        "UPDATE geo_distribution_targets_v1 "
        "SET human_publish_status = 'awaiting_publish' "
        "WHERE draft_readback_status = 'draft_saved'"
    )

    with op.batch_alter_table("geo_reobservations_v1") as batch:
        batch.alter_column("run_id", existing_type=sa.Integer(), nullable=True)
        batch.alter_column("evidence_id", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("baseline_batch_id", sa.Integer()))
        batch.add_column(sa.Column("retest_batch_id", sa.Integer()))
        batch.add_column(sa.Column("retest_queue_job_id", sa.Integer()))
        batch.create_foreign_key(
            "fk_geo_reobservation_baseline_batch_v1",
            "geo_observation_batches_v1",
            ["baseline_batch_id"],
            ["id"],
        )
        batch.create_foreign_key(
            "fk_geo_reobservation_retest_batch_v1",
            "geo_observation_batches_v1",
            ["retest_batch_id"],
            ["id"],
        )
        batch.create_foreign_key(
            "fk_geo_reobservation_retest_queue_v1",
            "queue_jobs",
            ["retest_queue_job_id"],
            ["id"],
        )
        batch.add_column(
            sa.Column("status", sa.String(32), nullable=False, server_default="completed")
        )
        batch.add_column(sa.Column("scope_snapshot", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("baseline_metrics", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("retest_metrics", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("started_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("completed_at", sa.DateTime(timezone=True)))
        batch.create_index("ix_geo_reobservations_v1_baseline_batch_id", ["baseline_batch_id"])
        batch.create_index("ix_geo_reobservations_v1_retest_batch_id", ["retest_batch_id"])
        batch.create_index("ix_geo_reobservations_v1_retest_queue_job_id", ["retest_queue_job_id"])
        batch.create_index("ix_geo_reobservations_v1_status", ["status"])


def downgrade() -> None:
    # New comparable retests do not have a single legacy run/evidence pair.
    # They cannot be represented by the previous schema, so remove only those
    # rows when an operator explicitly downgrades this migration.
    op.execute(
        "DELETE FROM geo_reobservations_v1 "
        "WHERE run_id IS NULL OR evidence_id IS NULL"
    )
    with op.batch_alter_table("geo_reobservations_v1") as batch:
        for index in (
            "ix_geo_reobservations_v1_status",
            "ix_geo_reobservations_v1_retest_queue_job_id",
            "ix_geo_reobservations_v1_retest_batch_id",
            "ix_geo_reobservations_v1_baseline_batch_id",
        ):
            batch.drop_index(index)
        for constraint in (
            "fk_geo_reobservation_retest_queue_v1",
            "fk_geo_reobservation_retest_batch_v1",
            "fk_geo_reobservation_baseline_batch_v1",
        ):
            batch.drop_constraint(constraint, type_="foreignkey")
        for column in (
            "completed_at",
            "started_at",
            "retest_metrics",
            "baseline_metrics",
            "scope_snapshot",
            "status",
            "retest_queue_job_id",
            "retest_batch_id",
            "baseline_batch_id",
        ):
            batch.drop_column(column)
        batch.alter_column("run_id", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("evidence_id", existing_type=sa.Integer(), nullable=False)

    with op.batch_alter_table("geo_distribution_targets_v1") as batch:
        batch.drop_index("ix_geo_distribution_targets_v1_published_by_user_id")
        batch.drop_index("ix_geo_distribution_targets_v1_human_publish_status")
        batch.drop_constraint("fk_geo_distribution_target_published_by_v1", type_="foreignkey")
        for column in (
            "published_by_user_id",
            "published_at",
            "publication_verification_status",
            "public_url",
            "human_publish_status",
        ):
            batch.drop_column(column)
