"""Add persisted opportunity, content and distribution contracts.

Revision ID: 20260807_0018
Revises: 20260806_0017
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260807_0018"
down_revision = "20260806_0017"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def upgrade() -> None:
    op.create_table(
        "geo_action_opportunities_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("opportunity_type", sa.String(40), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("priority_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("priority_label", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("evidence_strength", sa.Float(), nullable=False, server_default="0"),
        sa.Column("source_gap_type", sa.String(40)),
        sa.Column("recommended_asset_type", sa.String(40), nullable=False, server_default="article"),
        sa.Column("recommended_platforms", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("scope_snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("rule_version", sa.String(40), nullable=False, server_default="opportunity.v1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("first_seen_batch_id", sa.Integer(), sa.ForeignKey("geo_observation_batches_v1.id")),
        sa.Column("latest_seen_batch_id", sa.Integer(), sa.ForeignKey("geo_observation_batches_v1.id")),
        *_timestamps(),
        sa.UniqueConstraint("workspace_id", "fingerprint", name="uq_geo_action_opportunity_fingerprint_v1"),
    )
    for column in ("workspace_id", "opportunity_type", "status", "first_seen_batch_id", "latest_seen_batch_id"):
        op.create_index(f"ix_geo_action_opportunities_v1_{column}", "geo_action_opportunities_v1", [column])

    op.create_table(
        "geo_action_opportunity_evidence_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("opportunity_id", sa.Integer(), sa.ForeignKey("geo_action_opportunities_v1.id"), nullable=False),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("geo_observation_batches_v1.id")),
        sa.Column("observation_task_id", sa.Integer(), sa.ForeignKey("geo_observation_tasks_v1.id")),
        sa.Column("evidence_id", sa.Integer(), sa.ForeignKey("geo_evidence_v1.id"), nullable=False),
        sa.Column("question_plan_id", sa.Integer(), sa.ForeignKey("geo_question_plans_v1.id"), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("llm_providers.id")),
        sa.Column("model_key", sa.String(120), nullable=False),
        sa.Column("signal_type", sa.String(40), nullable=False),
        sa.Column("signal_value", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("source_url", sa.String(1500)),
        sa.Column("competitor_entity_id", sa.Integer()),
        *_timestamps(),
        sa.UniqueConstraint("opportunity_id", "evidence_id", name="uq_geo_action_opportunity_evidence_v1"),
    )
    for column in ("opportunity_id", "workspace_id", "batch_id", "observation_task_id", "evidence_id", "question_plan_id", "provider_id", "evidence_hash"):
        op.create_index(f"ix_geo_action_opportunity_evidence_v1_{column}", "geo_action_opportunity_evidence_v1", [column])

    op.create_table(
        "geo_action_events_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("action_id", sa.Integer(), sa.ForeignKey("geo_optimization_actions_v1.id")),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("from_stage", sa.String(32)),
        sa.Column("to_stage", sa.String(32)),
        sa.Column("actor_type", sa.String(32), nullable=False, server_default="user"),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("queue_jobs.id")),
        sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"),
        *_timestamps(),
    )
    for column in ("workspace_id", "action_id", "event_type", "actor_user_id", "job_id"):
        op.create_index(f"ix_geo_action_events_v1_{column}", "geo_action_events_v1", [column])

    with op.batch_alter_table("geo_optimization_actions_v1") as batch:
        batch.add_column(sa.Column("opportunity_id", sa.Integer()))
        batch.create_foreign_key(
            "fk_geo_optimization_action_opportunity_v1",
            "geo_action_opportunities_v1",
            ["opportunity_id"],
            ["id"],
        )
        batch.add_column(sa.Column("stage", sa.String(32), nullable=False, server_default="selected"))
        batch.add_column(sa.Column("baseline_snapshot", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("selected_scope", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("blocked_reason", sa.Text()))
        batch.add_column(sa.Column("selected_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_geo_optimization_actions_v1_opportunity_id", "geo_optimization_actions_v1", ["opportunity_id"])
    op.create_index("ix_geo_optimization_actions_v1_stage", "geo_optimization_actions_v1", ["stage"])

    op.create_table(
        "geo_prompt_templates_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("prompt_key", sa.String(120), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("purpose", sa.String(80), nullable=False),
        sa.Column("platform_key", sa.String(80)),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("user_template", sa.Text(), nullable=False),
        sa.Column("input_schema", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("output_schema", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("temperature", sa.Float(), nullable=False, server_default="0.2"),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False, server_default="2400"),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint("prompt_key", "version", name="uq_geo_prompt_template_key_version_v1"),
    )
    for column in ("prompt_key", "platform_key", "status"):
        op.create_index(f"ix_geo_prompt_templates_v1_{column}", "geo_prompt_templates_v1", [column])

    op.create_table(
        "geo_content_briefs_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("action_id", sa.Integer(), sa.ForeignKey("geo_optimization_actions_v1.id"), nullable=False),
        sa.Column("question_plan_id", sa.Integer(), sa.ForeignKey("geo_question_plans_v1.id")),
        sa.Column("audience", sa.String(160), nullable=False),
        sa.Column("intent", sa.String(80), nullable=False),
        sa.Column("asset_type", sa.String(40), nullable=False, server_default="article"),
        sa.Column("required_sections", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("brand_fact_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("evidence_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("source_urls", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("required_claims", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("forbidden_claims", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("open_questions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("prompt_template_id", sa.Integer(), sa.ForeignKey("geo_prompt_templates_v1.id")),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="ready"),
        *_timestamps(),
    )
    for column in ("workspace_id", "action_id", "question_plan_id", "input_fingerprint", "status"):
        op.create_index(f"ix_geo_content_briefs_v1_{column}", "geo_content_briefs_v1", [column])

    op.create_table(
        "geo_content_assets_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("brief_id", sa.Integer(), sa.ForeignKey("geo_content_briefs_v1.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("body_markdown", sa.Text(), nullable=False),
        sa.Column("content_fingerprint", sa.String(64), nullable=False),
        sa.Column("model_provider_id", sa.Integer(), sa.ForeignKey("llm_providers.id")),
        sa.Column("model_name", sa.String(120)),
        sa.Column("prompt_template_id", sa.Integer(), sa.ForeignKey("geo_prompt_templates_v1.id")),
        sa.Column("prompt_hash", sa.String(64)),
        sa.Column("raw_artifact_uri", sa.String(1500)),
        sa.Column("generation_usage", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        *_timestamps(),
        sa.UniqueConstraint("brief_id", "version", name="uq_geo_content_asset_brief_version_v1"),
    )
    for column in ("workspace_id", "brief_id", "content_fingerprint", "status"):
        op.create_index(f"ix_geo_content_assets_v1_{column}", "geo_content_assets_v1", [column])

    op.create_table(
        "geo_content_claims_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("content_asset_id", sa.Integer(), sa.ForeignKey("geo_content_assets_v1.id"), nullable=False),
        sa.Column("claim_key", sa.String(120), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("support_type", sa.String(40), nullable=False),
        sa.Column("support_id", sa.Integer()),
        sa.Column("source_url", sa.String(1500)),
        sa.Column("verification_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("introduced_by_model", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("review_note", sa.Text()),
        *_timestamps(),
    )
    op.create_index("ix_geo_content_claims_v1_content_asset_id", "geo_content_claims_v1", ["content_asset_id"])

    op.create_table(
        "geo_platform_variants_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("content_asset_id", sa.Integer(), sa.ForeignKey("geo_content_assets_v1.id"), nullable=False),
        sa.Column("platform_key", sa.String(80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("policy_version", sa.String(40), nullable=False, server_default="platform.v1"),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("body_markdown", sa.Text(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("category", sa.String(80)),
        sa.Column("image_manifest", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("adaptation_contract", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("content_fingerprint", sa.String(64), nullable=False),
        sa.Column("prompt_template_id", sa.Integer(), sa.ForeignKey("geo_prompt_templates_v1.id")),
        sa.Column("prompt_hash", sa.String(64)),
        sa.Column("status", sa.String(32), nullable=False, server_default="ready"),
        *_timestamps(),
        sa.UniqueConstraint("content_asset_id", "platform_key", "version", name="uq_geo_platform_variant_v1"),
    )
    for column in ("workspace_id", "content_asset_id", "platform_key", "content_fingerprint", "status"):
        op.create_index(f"ix_geo_platform_variants_v1_{column}", "geo_platform_variants_v1", [column])

    op.create_table(
        "geo_content_reviews_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("subject_type", sa.String(40), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("review_type", sa.String(40), nullable=False),
        sa.Column("verdict", sa.String(32), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("issues", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("users.id")),
        *_timestamps(),
    )
    for column in ("workspace_id", "subject_id", "reviewer_id"):
        op.create_index(f"ix_geo_content_reviews_v1_{column}", "geo_content_reviews_v1", [column])

    op.create_table(
        "geo_distribution_runs_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("action_id", sa.Integer(), sa.ForeignKey("geo_optimization_actions_v1.id")),
        sa.Column("content_asset_id", sa.Integer(), sa.ForeignKey("geo_content_assets_v1.id")),
        sa.Column("requested_platforms", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("stage", sa.String(32), nullable=False, server_default="requested"),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        *_timestamps(),
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_geo_distribution_idempotency_v1"),
    )
    for column in ("workspace_id", "action_id", "content_asset_id", "stage", "status", "requested_by_user_id"):
        op.create_index(f"ix_geo_distribution_runs_v1_{column}", "geo_distribution_runs_v1", [column])

    op.create_table(
        "geo_distribution_targets_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("distribution_run_id", sa.Integer(), sa.ForeignKey("geo_distribution_runs_v1.id"), nullable=False),
        sa.Column("platform_variant_id", sa.Integer(), sa.ForeignKey("geo_platform_variants_v1.id")),
        sa.Column("platform_key", sa.String(80), nullable=False),
        sa.Column("adapter_version", sa.String(40), nullable=False, server_default="mcp-adapter.v1"),
        sa.Column("request_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("draft_readback_status", sa.String(32), nullable=False, server_default="not_started"),
        sa.Column("candidate_draft_url", sa.String(1500)),
        sa.Column("draft_url", sa.String(1500)),
        sa.Column("external_draft_id", sa.String(255)),
        sa.Column("request_fingerprint", sa.String(64)),
        sa.Column("response_artifact_uri", sa.String(1500)),
        sa.Column("readback_artifact_uri", sa.String(1500)),
        sa.Column("waiting_human_reason", sa.Text()),
        sa.Column("blocked_reason", sa.Text()),
        sa.Column("last_error_code", sa.String(80)),
        sa.Column("final_action_clicked", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        *_timestamps(),
    )
    for column in ("distribution_run_id", "platform_variant_id", "platform_key", "request_fingerprint"):
        op.create_index(f"ix_geo_distribution_targets_v1_{column}", "geo_distribution_targets_v1", [column])


def downgrade() -> None:
    op.drop_index("ix_geo_optimization_actions_v1_stage", table_name="geo_optimization_actions_v1")
    op.drop_index("ix_geo_optimization_actions_v1_opportunity_id", table_name="geo_optimization_actions_v1")
    with op.batch_alter_table("geo_optimization_actions_v1") as batch:
        for column in ("completed_at", "selected_at", "blocked_reason", "selected_scope", "baseline_snapshot", "stage", "opportunity_id"):
            batch.drop_column(column)
    op.drop_table("geo_distribution_targets_v1")
    op.drop_table("geo_distribution_runs_v1")
    op.drop_table("geo_content_reviews_v1")
    op.drop_table("geo_platform_variants_v1")
    op.drop_table("geo_content_claims_v1")
    op.drop_table("geo_content_assets_v1")
    op.drop_table("geo_content_briefs_v1")
    op.drop_table("geo_prompt_templates_v1")
    op.drop_table("geo_action_events_v1")
    op.drop_table("geo_action_opportunity_evidence_v1")
    op.drop_table("geo_action_opportunities_v1")
