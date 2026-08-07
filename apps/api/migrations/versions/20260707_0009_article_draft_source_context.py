"""add article draft source context

Revision ID: 20260707_0009
Revises: 20260707_0008
Create Date: 2026-07-07
"""

from alembic import op
import sqlalchemy as sa


revision = "20260707_0009"
down_revision = "20260707_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("article_drafts")}
    if "source_context" not in columns:
        op.add_column("article_drafts", sa.Column("source_context", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("article_drafts")}
    if "source_context" in columns:
        op.drop_column("article_drafts", "source_context")
