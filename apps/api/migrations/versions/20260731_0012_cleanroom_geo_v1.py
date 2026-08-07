"""Add clean-room Spring Yuan GEO V1 product tables.

Revision ID: 20260731_0012
Revises: 20260731_0011
"""

from alembic import op
import sqlalchemy as sa


revision = "20260731_0012"
down_revision = "20260731_0011"
branch_labels = None
depends_on = None


def timestamp_columns():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    ]


def upgrade() -> None:
    op.create_table("geo_workspaces_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False, unique=True),
        sa.Column("brand_name", sa.String(length=255), nullable=False),
        sa.Column("brand_aliases", sa.JSON(), nullable=False),
        sa.Column("website_url", sa.String(length=1000)),
        sa.Column("status", sa.String(length=32), nullable=False),
        *timestamp_columns(),
    )
    op.create_index("ix_geo_workspaces_v1_company_id", "geo_workspaces_v1", ["company_id"])
    op.create_index("ix_geo_workspaces_v1_slug", "geo_workspaces_v1", ["slug"])
    op.create_index("ix_geo_workspaces_v1_status", "geo_workspaces_v1", ["status"])
    op.create_table("geo_question_plans_v1",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False), sa.Column("journey_stage", sa.String(length=40), nullable=False),
        sa.Column("importance", sa.Integer(), nullable=False), sa.Column("is_brand_query", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False), sa.Column("prompt_version", sa.String(length=50), nullable=False), *timestamp_columns(),
    )
    op.create_index("ix_geo_question_plans_v1_workspace_id", "geo_question_plans_v1", ["workspace_id"])
    op.create_table("geo_observation_runs_v1",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("adapter_key", sa.String(length=80), nullable=False), sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("request_context", sa.JSON(), nullable=False), sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("completed_at", sa.DateTime(timezone=True)), sa.Column("failure_reason", sa.Text()), *timestamp_columns(),
    )
    op.create_index("ix_geo_observation_runs_v1_workspace_id", "geo_observation_runs_v1", ["workspace_id"])
    op.create_index("ix_geo_observation_runs_v1_status", "geo_observation_runs_v1", ["status"])
    op.create_table("geo_evidence_v1",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("geo_observation_runs_v1.id"), nullable=False), sa.Column("question_plan_id", sa.Integer(), sa.ForeignKey("geo_question_plans_v1.id"), nullable=False),
        sa.Column("model_key", sa.String(length=120), nullable=False), sa.Column("model_label", sa.String(length=120), nullable=False), sa.Column("prompt_version", sa.String(length=50), nullable=False),
        sa.Column("sample_mode", sa.String(length=40), nullable=False), sa.Column("evidence_level", sa.String(length=32), nullable=False), sa.Column("collection_method", sa.String(length=40), nullable=False),
        sa.Column("evidence_kind", sa.String(length=40), nullable=False), sa.Column("is_real_provider_evidence", sa.Boolean(), nullable=False), sa.Column("brand_status", sa.String(length=32), nullable=False), sa.Column("brand_position", sa.Integer()),
        sa.Column("competitor_positions", sa.JSON(), nullable=False), sa.Column("answer_text", sa.Text(), nullable=False), sa.Column("answer_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("source_items", sa.JSON(), nullable=False), sa.Column("sampling_environment", sa.JSON(), nullable=False), sa.Column("raw_artifact_uri", sa.String(length=1500)), sa.Column("screenshot_uri", sa.String(length=1500)), sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False), *timestamp_columns(),
    )
    for name, columns in (("ix_geo_evidence_v1_workspace_id", ["workspace_id"]), ("ix_geo_evidence_v1_run_id", ["run_id"]), ("ix_geo_evidence_v1_question_plan_id", ["question_plan_id"]), ("ix_geo_evidence_v1_answer_hash", ["answer_hash"])):
        op.create_index(name, "geo_evidence_v1", columns)
    op.create_table("geo_scorecards_v1",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False), sa.Column("run_id", sa.Integer(), sa.ForeignKey("geo_observation_runs_v1.id"), nullable=False),
        sa.Column("scoring_version", sa.String(length=50), nullable=False), sa.Column("input_fingerprint", sa.String(length=64), nullable=False), sa.Column("metrics", sa.JSON(), nullable=False), sa.Column("explanation", sa.JSON(), nullable=False), *timestamp_columns(),
    )
    op.create_index("ix_geo_scorecards_v1_workspace_id", "geo_scorecards_v1", ["workspace_id"])
    op.create_index("ix_geo_scorecards_v1_input_fingerprint", "geo_scorecards_v1", ["input_fingerprint"])
    op.create_table("geo_optimization_actions_v1",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("question_plan_id", sa.Integer(), sa.ForeignKey("geo_question_plans_v1.id")), sa.Column("source_evidence_id", sa.Integer(), sa.ForeignKey("geo_evidence_v1.id")),
        sa.Column("title", sa.String(length=255), nullable=False), sa.Column("rationale", sa.Text(), nullable=False), sa.Column("hypothesis", sa.Text()), sa.Column("priority", sa.String(length=20), nullable=False), sa.Column("status", sa.String(length=32), nullable=False), *timestamp_columns(),
    )
    op.create_index("ix_geo_optimization_actions_v1_workspace_id", "geo_optimization_actions_v1", ["workspace_id"])
    op.create_index("ix_geo_optimization_actions_v1_status", "geo_optimization_actions_v1", ["status"])
    op.create_table("geo_reobservations_v1",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("action_id", sa.Integer(), sa.ForeignKey("geo_optimization_actions_v1.id"), nullable=False, unique=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False), sa.Column("run_id", sa.Integer(), sa.ForeignKey("geo_observation_runs_v1.id"), nullable=False), sa.Column("evidence_id", sa.Integer(), sa.ForeignKey("geo_evidence_v1.id"), nullable=False),
        sa.Column("conclusion", sa.Text(), nullable=False), sa.Column("measured_delta", sa.JSON(), nullable=False), *timestamp_columns(),
    )
    op.create_index("ix_geo_reobservations_v1_action_id", "geo_reobservations_v1", ["action_id"])
    op.create_index("ix_geo_reobservations_v1_workspace_id", "geo_reobservations_v1", ["workspace_id"])
    op.create_table("geo_brand_facts_v1",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False), sa.Column("statement", sa.Text(), nullable=False), sa.Column("source_url", sa.String(length=1000)), sa.Column("status", sa.String(length=32), nullable=False), *timestamp_columns(),
    )
    op.create_index("ix_geo_brand_facts_v1_workspace_id", "geo_brand_facts_v1", ["workspace_id"])


def downgrade() -> None:
    for table in ("geo_brand_facts_v1", "geo_reobservations_v1", "geo_optimization_actions_v1", "geo_scorecards_v1", "geo_evidence_v1", "geo_observation_runs_v1", "geo_question_plans_v1", "geo_workspaces_v1"):
        op.drop_table(table)
