"""Add actionable work information to collaboration threads.

Revision ID: 20260827_0037
Revises: 20260827_0036
"""

from alembic import op
import sqlalchemy as sa


revision = "20260827_0037"
down_revision = "20260827_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = "geo_collaboration_threads_v1"
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns(table)}
    # SQLite cannot add a foreign-key constraint with ALTER TABLE. Membership is
    # still validated by the application; fresh PostgreSQL installs also get the FK.
    if "assignee_user_id" not in columns:
        op.add_column(table, sa.Column("assignee_user_id", sa.Integer()))
    if bind.dialect.name != "sqlite":
        foreign_keys = {item.get("name") for item in inspector.get_foreign_keys(table)}
        if "fk_geo_collaboration_threads_v1_assignee_user_id" not in foreign_keys:
            op.create_foreign_key(
                "fk_geo_collaboration_threads_v1_assignee_user_id",
                table,
                "users",
                ["assignee_user_id"],
                ["id"],
            )
    if "start_at" not in columns:
        op.add_column(table, sa.Column("start_at", sa.DateTime(timezone=True)))
    if "due_at" not in columns:
        op.add_column(table, sa.Column("due_at", sa.DateTime(timezone=True)))
    if "participant_user_ids" not in columns:
        op.add_column(
            table,
            sa.Column("participant_user_ids", sa.JSON(), nullable=False, server_default="[]"),
        )
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table)}
    for column in ("assignee_user_id", "start_at", "due_at"):
        index_name = f"ix_{table}_{column}"
        if index_name not in indexes:
            op.create_index(index_name, table, [column])


def downgrade() -> None:
    table = "geo_collaboration_threads_v1"
    for column in ("due_at", "start_at", "assignee_user_id"):
        op.drop_index(f"ix_{table}_{column}", table_name=table)
    for column in ("participant_user_ids", "due_at", "start_at", "assignee_user_id"):
        op.drop_column(table, column)
