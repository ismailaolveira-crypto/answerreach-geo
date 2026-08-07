"""add review rules and snapshots

Revision ID: 20260706_0007
Revises: 20260706_0006
Create Date: 2026-07-06
"""

from alembic import op
import sqlalchemy as sa


revision = "20260706_0007"
down_revision = "20260706_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "review_rules" not in tables:
        op.create_table(
            "review_rules",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("rule_key", sa.String(length=100), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("applies_to", sa.String(length=50), nullable=False, server_default="article"),
            sa.Column("max_score", sa.Integer(), nullable=False, server_default="10"),
            sa.Column("weight", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("checks_json", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_review_rules_id"), "review_rules", ["id"], unique=False)
        op.create_index(op.f("ix_review_rules_rule_key"), "review_rules", ["rule_key"], unique=False)
        op.create_index(op.f("ix_review_rules_applies_to"), "review_rules", ["applies_to"], unique=False)
        op.create_index(op.f("ix_review_rules_status"), "review_rules", ["status"], unique=False)

    for table_name in ("article_reviews", "content_asset_reviews"):
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if "review_rule_snapshot" not in columns:
            op.add_column(table_name, sa.Column("review_rule_snapshot", sa.JSON(), nullable=True))
            op.execute(sa.text(f"UPDATE {table_name} SET review_rule_snapshot = '{{}}' WHERE review_rule_snapshot IS NULL"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table_name in ("content_asset_reviews", "article_reviews"):
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if "review_rule_snapshot" in columns:
            op.drop_column(table_name, "review_rule_snapshot")
    if "review_rules" in set(inspector.get_table_names()):
        op.drop_table("review_rules")
