"""Add scheduled GEO observations and evidence-linked change alerts.

Revision ID: 20260824_0031
Revises: 20260824_0030
"""

from alembic import op
import sqlalchemy as sa


revision = "20260824_0031"
down_revision = "20260824_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_observation_schedules_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("cadence", sa.String(24), nullable=False, server_default="daily"),
        sa.Column("weekdays", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("local_time", sa.String(5), nullable=False, server_default="09:00"),
        sa.Column("timezone_name", sa.String(80), nullable=False, server_default="Asia/Shanghai"),
        sa.Column("provider_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("question_plan_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("repeat_count", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("scope_snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("scope_fingerprint", sa.String(64), nullable=False),
        sa.Column("scope_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    for column in ("workspace_id", "status", "scope_fingerprint", "next_run_at", "created_by_user_id"):
        op.create_index(f"ix_geo_observation_schedules_v1_{column}", "geo_observation_schedules_v1", [column])

    op.create_table(
        "geo_observation_schedule_runs_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("schedule_id", sa.Integer(), sa.ForeignKey("geo_observation_schedules_v1.id"), nullable=False),
        sa.Column("window_key", sa.String(120), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("geo_observation_batches_v1.id")),
        sa.Column("baseline_batch_id", sa.Integer(), sa.ForeignKey("geo_observation_batches_v1.id")),
        sa.Column("scope_snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("scope_fingerprint", sa.String(64), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("schedule_id", "window_key", name="uq_geo_schedule_window_v1"),
    )
    for column in ("workspace_id", "schedule_id", "status", "batch_id", "baseline_batch_id", "scope_fingerprint"):
        op.create_index(f"ix_geo_observation_schedule_runs_v1_{column}", "geo_observation_schedule_runs_v1", [column])

    op.create_table(
        "geo_change_alerts_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("schedule_run_id", sa.Integer(), sa.ForeignKey("geo_observation_schedule_runs_v1.id")),
        sa.Column("alert_type", sa.String(80), nullable=False),
        sa.Column("severity", sa.String(24), nullable=False, server_default="warning"),
        sa.Column("status", sa.String(24), nullable=False, server_default="open"),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.String(160), nullable=False),
        sa.Column("baseline_batch_id", sa.Integer(), sa.ForeignKey("geo_observation_batches_v1.id")),
        sa.Column("current_batch_id", sa.Integer(), sa.ForeignKey("geo_observation_batches_v1.id")),
        sa.Column("scope_snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("completeness", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("metric_snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("evidence_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("suggested_action", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("converted_action_id", sa.Integer(), sa.ForeignKey("geo_optimization_actions_v1.id")),
        sa.Column("cooldown_until", sa.DateTime(timezone=True)),
        sa.Column("resolved_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    for column in ("workspace_id", "schedule_run_id", "alert_type", "severity", "status", "dedupe_key", "baseline_batch_id", "current_batch_id", "converted_action_id", "cooldown_until"):
        op.create_index(f"ix_geo_change_alerts_v1_{column}", "geo_change_alerts_v1", [column])


def downgrade() -> None:
    op.drop_table("geo_change_alerts_v1")
    op.drop_table("geo_observation_schedule_runs_v1")
    op.drop_table("geo_observation_schedules_v1")
