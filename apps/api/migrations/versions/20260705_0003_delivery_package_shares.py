"""add delivery package shares

Revision ID: 20260705_0003
Revises: 20260705_0002
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa

revision = "20260705_0003"
down_revision = "20260705_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delivery_package_shares",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_delivery_package_shares_id"), "delivery_package_shares", ["id"], unique=False)
    op.create_index(
        op.f("ix_delivery_package_shares_project_id"),
        "delivery_package_shares",
        ["project_id"],
        unique=False,
    )
    op.create_index(op.f("ix_delivery_package_shares_status"), "delivery_package_shares", ["status"], unique=False)
    op.create_index(op.f("ix_delivery_package_shares_token"), "delivery_package_shares", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_delivery_package_shares_token"), table_name="delivery_package_shares")
    op.drop_index(op.f("ix_delivery_package_shares_status"), table_name="delivery_package_shares")
    op.drop_index(op.f("ix_delivery_package_shares_project_id"), table_name="delivery_package_shares")
    op.drop_index(op.f("ix_delivery_package_shares_id"), table_name="delivery_package_shares")
    op.drop_table("delivery_package_shares")
