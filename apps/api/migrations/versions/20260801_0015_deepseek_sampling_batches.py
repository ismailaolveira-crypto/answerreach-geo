"""Add isolated browser profiles and durable DeepSeek sampling batches.

Revision ID: 20260801_0015
Revises: 20260801_0014
"""

from alembic import op
import sqlalchemy as sa


revision = "20260801_0015"
down_revision = "20260801_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("geo_browser_accounts_v1") as batch:
        batch.alter_column("ego_task_space_id", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("browser_profile_alias", sa.String(length=120)))
        batch.add_column(sa.Column("session_fingerprint", sa.String(length=64)))
        batch.add_column(sa.Column("isolation_verified_at", sa.DateTime(timezone=True)))
        batch.create_unique_constraint("uq_geo_browser_account_profile_v1", ["provider_key", "browser_profile_alias"])
        batch.create_unique_constraint("uq_geo_browser_account_fingerprint_v1", ["provider_key", "session_fingerprint"])
    op.execute(
        "UPDATE geo_browser_accounts_v1 SET status = 'onboarding', "
        "health_note = '需要重新连接独立浏览器 Profile 完成隔离验证', "
        "lease_token_hash = NULL, lease_worker_id = NULL, lease_run_id = NULL, lease_expires_at = NULL "
        "WHERE browser_profile_alias IS NULL OR session_fingerprint IS NULL"
    )

    op.create_table(
        "geo_sampling_batches_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("geo_observation_runs_v1.id"), nullable=False, unique=True),
        sa.Column("provider_key", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("account_count", sa.Integer(), nullable=False),
        sa.Column("question_count", sa.Integer(), nullable=False),
        sa.Column("repeat_count", sa.Integer(), nullable=False),
        sa.Column("total_samples", sa.Integer(), nullable=False),
        sa.Column("completed_samples", sa.Integer(), nullable=False),
        sa.Column("failed_samples", sa.Integer(), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("current_message", sa.String(length=500)),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_geo_sampling_batches_v1_workspace_id", "geo_sampling_batches_v1", ["workspace_id"])
    op.create_index("ix_geo_sampling_batches_v1_run_id", "geo_sampling_batches_v1", ["run_id"])
    op.create_index("ix_geo_sampling_batches_v1_status", "geo_sampling_batches_v1", ["status"])

    op.create_table(
        "geo_sampling_samples_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("geo_sampling_batches_v1.id"), nullable=False),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("geo_observation_runs_v1.id"), nullable=False),
        sa.Column("browser_account_id", sa.Integer(), sa.ForeignKey("geo_browser_accounts_v1.id"), nullable=False),
        sa.Column("question_plan_id", sa.Integer(), sa.ForeignKey("geo_question_plans_v1.id"), nullable=False),
        sa.Column("repeat_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("evidence_id", sa.Integer(), sa.ForeignKey("geo_evidence_v1.id"), unique=True),
        sa.Column("conversation_url", sa.String(length=1500)),
        sa.Column("raw_artifact_uri", sa.String(length=1500)),
        sa.Column("screenshot_uri", sa.String(length=1500)),
        sa.Column("error_code", sa.String(length=80)),
        sa.Column("error_detail", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("conversation_deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("batch_id", "browser_account_id", "question_plan_id", "repeat_index", name="uq_geo_sampling_sample_matrix_v1"),
    )
    for column in ("batch_id", "workspace_id", "run_id", "browser_account_id", "question_plan_id", "status"):
        op.create_index(f"ix_geo_sampling_samples_v1_{column}", "geo_sampling_samples_v1", [column])


def downgrade() -> None:
    op.drop_table("geo_sampling_samples_v1")
    op.drop_table("geo_sampling_batches_v1")
    with op.batch_alter_table("geo_browser_accounts_v1") as batch:
        batch.drop_constraint("uq_geo_browser_account_fingerprint_v1", type_="unique")
        batch.drop_constraint("uq_geo_browser_account_profile_v1", type_="unique")
        batch.drop_column("isolation_verified_at")
        batch.drop_column("session_fingerprint")
        batch.drop_column("browser_profile_alias")
        batch.alter_column("ego_task_space_id", existing_type=sa.Integer(), nullable=False)
