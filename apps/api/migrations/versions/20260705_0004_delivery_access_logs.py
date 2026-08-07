"""add delivery access logs

Revision ID: 20260705_0004
Revises: 20260705_0003
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa

revision = "20260705_0004"
down_revision = "20260705_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delivery_package_access_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("share_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("placement_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("actor_name", sa.String(length=255), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("detail_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["placement_id"], ["placement_records.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["share_id"], ["delivery_package_shares.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_delivery_package_access_logs_event_type"), "delivery_package_access_logs", ["event_type"], unique=False)
    op.create_index(op.f("ix_delivery_package_access_logs_id"), "delivery_package_access_logs", ["id"], unique=False)
    op.create_index(op.f("ix_delivery_package_access_logs_placement_id"), "delivery_package_access_logs", ["placement_id"], unique=False)
    op.create_index(op.f("ix_delivery_package_access_logs_project_id"), "delivery_package_access_logs", ["project_id"], unique=False)
    op.create_index(op.f("ix_delivery_package_access_logs_share_id"), "delivery_package_access_logs", ["share_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_delivery_package_access_logs_share_id"), table_name="delivery_package_access_logs")
    op.drop_index(op.f("ix_delivery_package_access_logs_project_id"), table_name="delivery_package_access_logs")
    op.drop_index(op.f("ix_delivery_package_access_logs_placement_id"), table_name="delivery_package_access_logs")
    op.drop_index(op.f("ix_delivery_package_access_logs_id"), table_name="delivery_package_access_logs")
    op.drop_index(op.f("ix_delivery_package_access_logs_event_type"), table_name="delivery_package_access_logs")
    op.drop_table("delivery_package_access_logs")
