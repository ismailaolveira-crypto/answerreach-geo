"""Add persisted local Codex agent runs, events and artifacts.

Revision ID: 20260808_0020
Revises: 20260807_0019
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260808_0020"
down_revision = "20260807_0019"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
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
    )


def upgrade() -> None:
    op.create_table(
        "geo_agent_runs_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("action_id", sa.Integer(), sa.ForeignKey("geo_optimization_actions_v1.id"), nullable=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("queue_jobs.id")),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("runtime_key", sa.String(50), nullable=False, server_default="local_codex"),
        sa.Column("model", sa.String(120)),
        sa.Column("codex_thread_id", sa.String(100)),
        sa.Column("codex_turn_id", sa.String(100)),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(40), nullable=False, server_default="queued"),
        sa.Column("selected_platforms", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("request_snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("result_snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("task_directory", sa.String(1500)),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.Text()),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    for column in (
        "workspace_id",
        "action_id",
        "job_id",
        "requested_by_user_id",
        "codex_thread_id",
        "codex_turn_id",
        "status",
        "stage",
    ):
        op.create_index(f"ix_geo_agent_runs_v1_{column}", "geo_agent_runs_v1", [column])

    op.create_table(
        "geo_agent_events_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("agent_run_id", sa.Integer(), sa.ForeignKey("geo_agent_runs_v1.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.UniqueConstraint("agent_run_id", "sequence", name="uq_geo_agent_event_sequence_v1"),
    )
    for column in ("workspace_id", "agent_run_id", "event_type", "stage"):
        op.create_index(f"ix_geo_agent_events_v1_{column}", "geo_agent_events_v1", [column])

    op.create_table(
        "geo_agent_artifacts_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("agent_run_id", sa.Integer(), sa.ForeignKey("geo_agent_runs_v1.id"), nullable=False),
        sa.Column("artifact_kind", sa.String(50), nullable=False),
        sa.Column("uri", sa.String(1500), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        *_timestamps(),
    )
    for column in ("workspace_id", "agent_run_id", "artifact_kind", "sha256"):
        op.create_index(f"ix_geo_agent_artifacts_v1_{column}", "geo_agent_artifacts_v1", [column])


def downgrade() -> None:
    op.drop_table("geo_agent_artifacts_v1")
    op.drop_table("geo_agent_events_v1")
    op.drop_table("geo_agent_runs_v1")
