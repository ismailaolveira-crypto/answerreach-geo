"""Separate public delivery viewing from confirmation authority.

Revision ID: 20260830_0040
Revises: 20260830_0039
"""

from alembic import op
import json
import sqlalchemy as sa


revision = "20260830_0040"
down_revision = "20260830_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    columns = {
        item["name"]
        for item in sa.inspect(bind).get_columns("delivery_package_shares")
    }
    if "confirmation_token_encrypted" not in columns:
        op.add_column(
            "delivery_package_shares",
            sa.Column("confirmation_token_encrypted", sa.Text()),
        )
    mention_table = "geo_collaboration_mentions_v1"
    if mention_table not in tables:
        op.create_table(
            mention_table,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "workspace_id",
                sa.Integer(),
                sa.ForeignKey("geo_workspaces_v1.id"),
                nullable=False,
            ),
            sa.Column(
                "thread_id",
                sa.Integer(),
                sa.ForeignKey("geo_collaboration_threads_v1.id"),
                nullable=False,
            ),
            sa.Column(
                "message_id",
                sa.Integer(),
                sa.ForeignKey("geo_collaboration_messages_v1.id"),
                nullable=False,
            ),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.UniqueConstraint(
                "message_id",
                "user_id",
                name="uq_geo_collaboration_mention_message_user_v1",
            ),
        )
        for column in ("workspace_id", "thread_id", "message_id", "user_id"):
            op.create_index(
                f"ix_geo_collab_mentions_{column}", mention_table, [column]
            )
        messages = sa.table(
            "geo_collaboration_messages_v1",
            sa.column("id", sa.Integer()),
            sa.column("workspace_id", sa.Integer()),
            sa.column("thread_id", sa.Integer()),
            sa.column("mention_user_ids", sa.JSON()),
        )
        mentions = sa.table(
            mention_table,
            sa.column("workspace_id", sa.Integer()),
            sa.column("thread_id", sa.Integer()),
            sa.column("message_id", sa.Integer()),
            sa.column("user_id", sa.Integer()),
        )
        for row in bind.execute(sa.select(messages)).mappings():
            raw_ids = row["mention_user_ids"] or []
            if isinstance(raw_ids, str):
                try:
                    raw_ids = json.loads(raw_ids)
                except json.JSONDecodeError:
                    raw_ids = []
            normalized_ids: set[int] = set()
            for value in raw_ids if isinstance(raw_ids, list) else []:
                try:
                    user_id = int(value)
                except (TypeError, ValueError):
                    continue
                if user_id > 0:
                    normalized_ids.add(user_id)
            for user_id in sorted(normalized_ids):
                bind.execute(
                    mentions.insert().values(
                        workspace_id=row["workspace_id"],
                        thread_id=row["thread_id"],
                        message_id=row["id"],
                        user_id=user_id,
                    )
                )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "geo_collaboration_mentions_v1" in tables:
        op.drop_table("geo_collaboration_mentions_v1")
    columns = {
        item["name"]
        for item in sa.inspect(bind).get_columns("delivery_package_shares")
    }
    if "confirmation_token_encrypted" in columns:
        op.drop_column("delivery_package_shares", "confirmation_token_encrypted")
