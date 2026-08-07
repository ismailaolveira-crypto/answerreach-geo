"""add placement delivery metadata

Revision ID: 20260705_0002
Revises: 20260704_0001
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa

revision = "20260705_0002"
down_revision = "20260704_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("placement_records", sa.Column("archive_note", sa.Text(), nullable=True))
    op.add_column(
        "placement_records",
        sa.Column("visibility", sa.String(length=50), nullable=False, server_default="internal"),
    )
    op.add_column(
        "placement_records",
        sa.Column("delivery_status", sa.String(length=50), nullable=False, server_default="not_delivered"),
    )
    op.create_index(op.f("ix_placement_records_visibility"), "placement_records", ["visibility"], unique=False)
    op.create_index(
        op.f("ix_placement_records_delivery_status"),
        "placement_records",
        ["delivery_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_placement_records_delivery_status"), table_name="placement_records")
    op.drop_index(op.f("ix_placement_records_visibility"), table_name="placement_records")
    op.drop_column("placement_records", "delivery_status")
    op.drop_column("placement_records", "visibility")
    op.drop_column("placement_records", "archive_note")
