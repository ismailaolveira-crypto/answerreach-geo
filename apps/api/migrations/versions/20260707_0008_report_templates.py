"""add report templates

Revision ID: 20260707_0008
Revises: 20260706_0007
Create Date: 2026-07-07
"""

from alembic import op
import sqlalchemy as sa


revision = "20260707_0008"
down_revision = "20260706_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "report_templates" not in tables:
        op.create_table(
            "report_templates",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("template_key", sa.String(length=100), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("applies_to", sa.String(length=50), nullable=False, server_default="maturity_report"),
            sa.Column("sections_json", sa.JSON(), nullable=True),
            sa.Column("scoring_json", sa.JSON(), nullable=True),
            sa.Column("delivery_checks_json", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_report_templates_id"), "report_templates", ["id"], unique=False)
        op.create_index(op.f("ix_report_templates_template_key"), "report_templates", ["template_key"], unique=False)
        op.create_index(op.f("ix_report_templates_applies_to"), "report_templates", ["applies_to"], unique=False)
        op.create_index(op.f("ix_report_templates_status"), "report_templates", ["status"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "report_templates" in set(inspector.get_table_names()):
        op.drop_index(op.f("ix_report_templates_status"), table_name="report_templates")
        op.drop_index(op.f("ix_report_templates_applies_to"), table_name="report_templates")
        op.drop_index(op.f("ix_report_templates_template_key"), table_name="report_templates")
        op.drop_index(op.f("ix_report_templates_id"), table_name="report_templates")
        op.drop_table("report_templates")
