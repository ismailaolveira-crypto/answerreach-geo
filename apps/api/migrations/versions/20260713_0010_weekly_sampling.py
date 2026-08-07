"""Add repeated sampling controls for weekly GEO evaluation.

Revision ID: 20260713_0010
Revises: 20260707_0009
"""

from alembic import op
import sqlalchemy as sa


revision = "20260713_0010"
down_revision = "20260707_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("crawl_tasks") as batch_op:
        batch_op.add_column(sa.Column("sample_runs_per_prompt", sa.Integer(), nullable=False, server_default="1"))
    with op.batch_alter_table("crawl_schedules") as batch_op:
        batch_op.add_column(sa.Column("sample_runs_per_prompt", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    with op.batch_alter_table("crawl_schedules") as batch_op:
        batch_op.drop_column("sample_runs_per_prompt")
    with op.batch_alter_table("crawl_tasks") as batch_op:
        batch_op.drop_column("sample_runs_per_prompt")
