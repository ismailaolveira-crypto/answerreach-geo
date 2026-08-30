"""Add persistent GEO Agent workspace conversations.

Revision ID: 20260830_0041
Revises: 20260830_0040
"""

from alembic import op
import sqlalchemy as sa


revision = "20260830_0041"
down_revision = "20260830_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_agent_conversations_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(160), nullable=False, server_default="新的 GEO 对话"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("runtime_key", sa.String(50), nullable=False, server_default="local_codex"),
        sa.Column("model", sa.String(120)),
        sa.Column("reasoning_effort", sa.String(20)),
        sa.Column("external_thread_id", sa.String(160)),
        sa.Column("context_snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    for column in ("workspace_id", "created_by_user_id", "status", "external_thread_id", "last_message_at"):
        op.create_index(f"ix_geo_agent_conversations_{column}", "geo_agent_conversations_v1", [column])

    op.create_table(
        "geo_agent_conversation_messages_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("geo_agent_conversations_v1.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="completed"),
        sa.Column("structured_payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("runtime_key", sa.String(50)),
        sa.Column("model", sa.String(120)),
        sa.Column("external_turn_id", sa.String(160)),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("queue_jobs.id")),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("conversation_id", "sequence", name="uq_geo_agent_conversation_message_sequence_v1"),
    )
    for column in ("workspace_id", "conversation_id", "role", "status", "external_turn_id", "job_id", "created_by_user_id"):
        op.create_index(f"ix_geo_agent_conversation_messages_{column}", "geo_agent_conversation_messages_v1", [column])

    op.create_table(
        "geo_agent_conversation_events_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("geo_agent_conversation_messages_v1.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("message_id", "sequence", name="uq_geo_agent_conversation_event_sequence_v1"),
    )
    for column in ("workspace_id", "message_id", "event_type", "stage"):
        op.create_index(f"ix_geo_agent_conversation_events_{column}", "geo_agent_conversation_events_v1", [column])


def downgrade() -> None:
    op.drop_table("geo_agent_conversation_events_v1")
    op.drop_table("geo_agent_conversation_messages_v1")
    op.drop_table("geo_agent_conversations_v1")
