"""add crawl task scope columns

Revision ID: 20260706_0006
Revises: 20260705_0005
Create Date: 2026-07-06
"""

from alembic import op
import sqlalchemy as sa

revision = "20260706_0006"
down_revision = "20260705_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("crawl_tasks")}
    if "target_question_ids" not in columns:
        op.add_column("crawl_tasks", sa.Column("target_question_ids", sa.JSON(), nullable=True))
    if "keyword_ids" not in columns:
        op.add_column("crawl_tasks", sa.Column("keyword_ids", sa.JSON(), nullable=True))
    op.execute(sa.text("UPDATE crawl_tasks SET target_question_ids = '[]' WHERE target_question_ids IS NULL"))
    op.execute(sa.text("UPDATE crawl_tasks SET keyword_ids = '[]' WHERE keyword_ids IS NULL"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("crawl_tasks")}
    if "keyword_ids" in columns:
        op.drop_column("crawl_tasks", "keyword_ids")
    if "target_question_ids" in columns:
        op.drop_column("crawl_tasks", "target_question_ids")
