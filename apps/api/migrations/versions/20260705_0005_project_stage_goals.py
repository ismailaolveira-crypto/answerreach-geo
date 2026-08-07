"""add project stage goals

Revision ID: 20260705_0005
Revises: 20260705_0004
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa

revision = "20260705_0005"
down_revision = "20260705_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("project_stage_goals"):
        op.create_table(
            "project_stage_goals",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("metric_key", sa.String(length=100), nullable=False),
            sa.Column("target_value", sa.Float(), nullable=False),
            sa.Column("baseline_value", sa.Float(), nullable=False),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("owner", sa.String(length=255), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    existing_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("project_stage_goals")}
    indexes = [
        (op.f("ix_project_stage_goals_due_at"), ["due_at"]),
        (op.f("ix_project_stage_goals_id"), ["id"]),
        (op.f("ix_project_stage_goals_metric_key"), ["metric_key"]),
        (op.f("ix_project_stage_goals_project_id"), ["project_id"]),
        (op.f("ix_project_stage_goals_status"), ["status"]),
    ]
    for name, columns in indexes:
        if name not in existing_indexes:
            op.create_index(name, "project_stage_goals", columns, unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_project_stage_goals_status"), table_name="project_stage_goals")
    op.drop_index(op.f("ix_project_stage_goals_project_id"), table_name="project_stage_goals")
    op.drop_index(op.f("ix_project_stage_goals_metric_key"), table_name="project_stage_goals")
    op.drop_index(op.f("ix_project_stage_goals_id"), table_name="project_stage_goals")
    op.drop_index(op.f("ix_project_stage_goals_due_at"), table_name="project_stage_goals")
    op.drop_table("project_stage_goals")
