"""Add the native GEO Article Assistant task protocol ledger.

Revision ID: 20260824_0033
Revises: 20260824_0032
"""

from alembic import op
import sqlalchemy as sa


revision = "20260824_0033"
down_revision = "20260824_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("geo_distribution_runs_v1") as batch_op:
        batch_op.add_column(sa.Column("assistant_protocol_version", sa.String(80)))
        batch_op.add_column(sa.Column("assistant_task_nonce_hash", sa.String(64)))
        batch_op.add_column(sa.Column("assistant_task_expires_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("assistant_content_fingerprint", sa.String(64)))
        batch_op.add_column(sa.Column("assistant_task_issued_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("assistant_operator_user_id", sa.Integer()))
        batch_op.create_foreign_key(
            "fk_geo_distribution_assistant_operator_v1",
            "users",
            ["assistant_operator_user_id"],
            ["id"],
        )
        batch_op.create_index(
            "ix_geo_distribution_runs_v1_assistant_task_nonce_hash",
            ["assistant_task_nonce_hash"],
        )
        batch_op.create_index(
            "ix_geo_distribution_runs_v1_assistant_content_fingerprint",
            ["assistant_content_fingerprint"],
        )
        batch_op.create_index(
            "ix_geo_distribution_runs_v1_assistant_operator_user_id",
            ["assistant_operator_user_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("geo_distribution_runs_v1") as batch_op:
        batch_op.drop_index("ix_geo_distribution_runs_v1_assistant_operator_user_id")
        batch_op.drop_index("ix_geo_distribution_runs_v1_assistant_content_fingerprint")
        batch_op.drop_index("ix_geo_distribution_runs_v1_assistant_task_nonce_hash")
        batch_op.drop_constraint("fk_geo_distribution_assistant_operator_v1", type_="foreignkey")
        batch_op.drop_column("assistant_operator_user_id")
        batch_op.drop_column("assistant_task_issued_at")
        batch_op.drop_column("assistant_content_fingerprint")
        batch_op.drop_column("assistant_task_expires_at")
        batch_op.drop_column("assistant_task_nonce_hash")
        batch_op.drop_column("assistant_protocol_version")
