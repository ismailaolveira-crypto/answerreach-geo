"""add durable login attempt throttling

Revision ID: 20260810_0027
Revises: 20260810_0026
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260810_0027"
down_revision: str | None = "20260810_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("auth_login_throttles"):
        return
    op.create_table(
        "auth_login_throttles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("key_hash", name="uq_auth_login_throttles_key_hash"),
    )
    op.create_index("ix_auth_login_throttles_key_hash", "auth_login_throttles", ["key_hash"])
    op.create_index("ix_auth_login_throttles_locked_until", "auth_login_throttles", ["locked_until"])


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("auth_login_throttles"):
        op.drop_table("auth_login_throttles")
