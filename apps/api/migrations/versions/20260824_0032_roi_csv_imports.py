"""Add ROI CSV preflight and import ledgers.

Revision ID: 20260824_0032
Revises: 20260824_0031
"""

from alembic import op
import sqlalchemy as sa


revision = "20260824_0032"
down_revision = "20260824_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_business_metric_import_batches_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="preflight"),
        sa.Column("mapping_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("imported_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("reversed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("workspace_id", "file_sha256", name="uq_geo_business_import_file_v1"),
    )
    for column in ("workspace_id", "file_sha256", "status", "created_by_user_id"):
        op.create_index(f"ix_geo_business_metric_import_batches_v1_{column}", "geo_business_metric_import_batches_v1", [column])
    op.create_table(
        "geo_business_metric_import_rows_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("import_batch_id", sa.Integer(), sa.ForeignKey("geo_business_metric_import_batches_v1.id"), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("record_id", sa.String(160)),
        sa.Column("normalized_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("errors_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("metric_entry_id", sa.Integer(), sa.ForeignKey("geo_business_metric_entries_v1.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("import_batch_id", "row_number", name="uq_geo_business_import_row_v1"),
    )
    for column in ("workspace_id", "import_batch_id", "record_id", "status", "metric_entry_id"):
        op.create_index(f"ix_geo_business_metric_import_rows_v1_{column}", "geo_business_metric_import_rows_v1", [column])
    with op.batch_alter_table("geo_business_metric_entries_v1") as batch_op:
        batch_op.add_column(sa.Column("import_batch_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("source_record_id", sa.String(160), nullable=True))
        batch_op.create_foreign_key(
            "fk_geo_business_entry_import_batch_v1",
            "geo_business_metric_import_batches_v1",
            ["import_batch_id"],
            ["id"],
        )
        batch_op.create_index("ix_geo_business_metric_entries_v1_import_batch_id", ["import_batch_id"])
        batch_op.create_index("ix_geo_business_metric_entries_v1_source_record_id", ["source_record_id"])


def downgrade() -> None:
    with op.batch_alter_table("geo_business_metric_entries_v1") as batch_op:
        batch_op.drop_index("ix_geo_business_metric_entries_v1_source_record_id")
        batch_op.drop_index("ix_geo_business_metric_entries_v1_import_batch_id")
        batch_op.drop_constraint("fk_geo_business_entry_import_batch_v1", type_="foreignkey")
        batch_op.drop_column("source_record_id")
        batch_op.drop_column("import_batch_id")
    op.drop_table("geo_business_metric_import_rows_v1")
    op.drop_table("geo_business_metric_import_batches_v1")
