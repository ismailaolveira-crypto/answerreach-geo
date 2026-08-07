from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)  # pyright: ignore[reportMissingImports]
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CleanRoomTimestamp:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )


class GeoWorkspace(CleanRoomTimestamp, Base):
    __tablename__ = "geo_workspaces_v1"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    brand_name: Mapped[str] = mapped_column(String(255), nullable=False)
    brand_aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    website_url: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)


class GeoWorkspaceSecret(CleanRoomTimestamp, Base):
    """Encrypted runtime credentials scoped to one GEO workspace.

    Plaintext values never leave the API process.  The UI receives only
    configured flags and timestamps, while workers resolve the value just
    before making an authorized external request.
    """

    __tablename__ = "geo_workspace_secrets_v1"
    __table_args__ = (
        UniqueConstraint("workspace_id", "secret_key", name="uq_geo_workspace_secret_key_v1"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    secret_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)


class GeoQuestionPlan(CleanRoomTimestamp, Base):
    __tablename__ = "geo_question_plans_v1"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    journey_stage: Mapped[str] = mapped_column(String(40), nullable=False, default="consideration")
    role: Mapped[str] = mapped_column(
        String(60), nullable=False, default="technical_lead", index=True
    )
    topic_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    importance: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    is_brand_query: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    source_evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_reason: Mapped[str | None] = mapped_column(Text)
    source_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cluster_id: Mapped[str | None] = mapped_column(String(100), index=True)
    similar_question_id: Mapped[int | None] = mapped_column(Integer, index=True)
    similarity: Mapped[float | None] = mapped_column(Float)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    template_variables: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_reason: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False, default="v1")


class GeoQuestionReview(CleanRoomTimestamp, Base):
    __tablename__ = "geo_question_reviews_v1"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    question_plan_id: Mapped[int] = mapped_column(
        ForeignKey("geo_question_plans_v1.id"), nullable=False, index=True
    )
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str | None] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class GeoObservationRun(CleanRoomTimestamp, Base):
    __tablename__ = "geo_observation_runs_v1"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    adapter_key: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    request_context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)


class GeoObservationBatch(CleanRoomTimestamp, Base):
    """Canonical batch ledger shared by every collection adapter.

    Queue jobs are execution details. This row is the durable product record
    used by history, analytics and recovery screens.
    """

    __tablename__ = "geo_observation_batches_v1"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    queue_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("queue_jobs.id"), unique=True, index=True
    )
    requested_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, default="official_api")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    provider_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repeat_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    total_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GeoObservationTask(CleanRoomTimestamp, Base):
    """One immutable matrix cell: model x question x repeat index."""

    __tablename__ = "geo_observation_tasks_v1"
    __table_args__ = (
        UniqueConstraint(
            "batch_id",
            "sample_key",
            name="uq_geo_observation_task_matrix_v1",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("geo_observation_batches_v1.id"), nullable=False, index=True
    )
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    queue_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("queue_jobs.id"), unique=True, index=True
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("geo_observation_runs_v1.id"), index=True
    )
    evidence_id: Mapped[int | None] = mapped_column(
        ForeignKey("geo_evidence_v1.id"), unique=True, index=True
    )
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("llm_providers.id"), index=True)
    provider_key: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_label: Mapped[str] = mapped_column(String(160), nullable=False)
    model_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    model_label: Mapped[str] = mapped_column(String(160), nullable=False)
    question_plan_id: Mapped[int] = mapped_column(
        ForeignKey("geo_question_plans_v1.id"), nullable=False, index=True
    )
    question_text_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    sample_key: Mapped[str] = mapped_column(String(160), nullable=False)
    repeat_index: Mapped[int] = mapped_column(Integer, nullable=False)
    repeat_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    observation_group_id: Mapped[str | None] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GeoEvidence(CleanRoomTimestamp, Base):
    __tablename__ = "geo_evidence_v1"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("geo_observation_runs_v1.id"), nullable=False, index=True
    )
    question_plan_id: Mapped[int] = mapped_column(
        ForeignKey("geo_question_plans_v1.id"), nullable=False, index=True
    )
    model_key: Mapped[str] = mapped_column(String(120), nullable=False)
    model_label: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False, default="v1")
    sample_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_level: Mapped[str] = mapped_column(String(32), nullable=False)
    collection_method: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    is_real_provider_evidence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    brand_status: Mapped[str] = mapped_column(String(32), nullable=False, default="absent")
    brand_position: Mapped[int | None] = mapped_column(Integer)
    competitor_positions: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    answer_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    source_items: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    sampling_environment: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    raw_artifact_uri: Mapped[str | None] = mapped_column(String(1500))
    screenshot_uri: Mapped[str | None] = mapped_column(String(1500))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GeoScorecard(CleanRoomTimestamp, Base):
    __tablename__ = "geo_scorecards_v1"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("geo_observation_runs_v1.id"), nullable=False, index=True
    )
    scoring_version: Mapped[str] = mapped_column(String(50), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    explanation: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class GeoOptimizationAction(CleanRoomTimestamp, Base):
    __tablename__ = "geo_optimization_actions_v1"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    question_plan_id: Mapped[int | None] = mapped_column(ForeignKey("geo_question_plans_v1.id"))
    source_evidence_id: Mapped[int | None] = mapped_column(ForeignKey("geo_evidence_v1.id"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    hypothesis: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed", index=True)
    opportunity_id: Mapped[int | None] = mapped_column(
        ForeignKey("geo_action_opportunities_v1.id"), index=True
    )
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="selected", index=True)
    baseline_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    selected_scope: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    blocked_reason: Mapped[str | None] = mapped_column(Text)
    selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GeoActionOpportunity(CleanRoomTimestamp, Base):
    __tablename__ = "geo_action_opportunities_v1"
    __table_args__ = (
        UniqueConstraint("workspace_id", "fingerprint", name="uq_geo_action_opportunity_fingerprint_v1"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    opportunity_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    priority_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    priority_label: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    evidence_strength: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    source_gap_type: Mapped[str | None] = mapped_column(String(40))
    recommended_asset_type: Mapped[str] = mapped_column(
        String(40), nullable=False, default="article"
    )
    recommended_platforms: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    scope_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    rule_version: Mapped[str] = mapped_column(String(40), nullable=False, default="opportunity.v1")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open", index=True)
    first_seen_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("geo_observation_batches_v1.id"), index=True
    )
    latest_seen_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("geo_observation_batches_v1.id"), index=True
    )


class GeoActionOpportunityEvidence(CleanRoomTimestamp, Base):
    __tablename__ = "geo_action_opportunity_evidence_v1"
    __table_args__ = (
        UniqueConstraint(
            "opportunity_id", "evidence_id", name="uq_geo_action_opportunity_evidence_v1"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("geo_action_opportunities_v1.id"), nullable=False, index=True
    )
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("geo_observation_batches_v1.id"), index=True
    )
    observation_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("geo_observation_tasks_v1.id"), index=True
    )
    evidence_id: Mapped[int] = mapped_column(
        ForeignKey("geo_evidence_v1.id"), nullable=False, index=True
    )
    question_plan_id: Mapped[int] = mapped_column(
        ForeignKey("geo_question_plans_v1.id"), nullable=False, index=True
    )
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("llm_providers.id"), index=True)
    model_key: Mapped[str] = mapped_column(String(120), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(40), nullable=False)
    signal_value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_url: Mapped[str | None] = mapped_column(String(1500))
    competitor_entity_id: Mapped[int | None] = mapped_column(Integer)


class GeoActionEvent(CleanRoomTimestamp, Base):
    __tablename__ = "geo_action_events_v1"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    action_id: Mapped[int | None] = mapped_column(
        ForeignKey("geo_optimization_actions_v1.id"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    from_stage: Mapped[str | None] = mapped_column(String(32))
    to_stage: Mapped[str | None] = mapped_column(String(32))
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("queue_jobs.id"), index=True)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class GeoPromptTemplate(CleanRoomTimestamp, Base):
    __tablename__ = "geo_prompt_templates_v1"
    __table_args__ = (
        UniqueConstraint("prompt_key", "version", name="uq_geo_prompt_template_key_version_v1"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    prompt_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    purpose: Mapped[str] = mapped_column(String(80), nullable=False)
    platform_key: Mapped[str | None] = mapped_column(String(80), index=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_template: Mapped[str] = mapped_column(Text, nullable=False)
    input_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    output_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.2)
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=2400)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GeoContentBrief(CleanRoomTimestamp, Base):
    __tablename__ = "geo_content_briefs_v1"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    action_id: Mapped[int] = mapped_column(
        ForeignKey("geo_optimization_actions_v1.id"), nullable=False, index=True
    )
    question_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("geo_question_plans_v1.id"), index=True
    )
    audience: Mapped[str] = mapped_column(String(160), nullable=False)
    intent: Mapped[str] = mapped_column(String(80), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(40), nullable=False, default="article")
    required_sections: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    brand_fact_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    evidence_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    source_urls: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    required_claims: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    forbidden_claims: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    open_questions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    prompt_template_id: Mapped[int | None] = mapped_column(ForeignKey("geo_prompt_templates_v1.id"))
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready", index=True)


class GeoContentAsset(CleanRoomTimestamp, Base):
    __tablename__ = "geo_content_assets_v1"
    __table_args__ = (
        UniqueConstraint("brief_id", "version", name="uq_geo_content_asset_brief_version_v1"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    brief_id: Mapped[int] = mapped_column(
        ForeignKey("geo_content_briefs_v1.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_provider_id: Mapped[int | None] = mapped_column(ForeignKey("llm_providers.id"))
    model_name: Mapped[str | None] = mapped_column(String(120))
    prompt_template_id: Mapped[int | None] = mapped_column(ForeignKey("geo_prompt_templates_v1.id"))
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    raw_artifact_uri: Mapped[str | None] = mapped_column(String(1500))
    generation_usage: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)


class GeoContentClaim(CleanRoomTimestamp, Base):
    __tablename__ = "geo_content_claims_v1"

    id: Mapped[int] = mapped_column(primary_key=True)
    content_asset_id: Mapped[int] = mapped_column(
        ForeignKey("geo_content_assets_v1.id"), nullable=False, index=True
    )
    claim_key: Mapped[str] = mapped_column(String(120), nullable=False)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    support_type: Mapped[str] = mapped_column(String(40), nullable=False)
    support_id: Mapped[int | None] = mapped_column(Integer)
    source_url: Mapped[str | None] = mapped_column(String(1500))
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    introduced_by_model: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    review_note: Mapped[str | None] = mapped_column(Text)


class GeoPlatformVariant(CleanRoomTimestamp, Base):
    __tablename__ = "geo_platform_variants_v1"
    __table_args__ = (
        UniqueConstraint(
            "content_asset_id", "platform_key", "version", name="uq_geo_platform_variant_v1"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    content_asset_id: Mapped[int] = mapped_column(
        ForeignKey("geo_content_assets_v1.id"), nullable=False, index=True
    )
    platform_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    policy_version: Mapped[str] = mapped_column(String(40), nullable=False, default="platform.v1")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    category: Mapped[str | None] = mapped_column(String(80))
    image_manifest: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    adaptation_contract: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    prompt_template_id: Mapped[int | None] = mapped_column(ForeignKey("geo_prompt_templates_v1.id"))
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready", index=True)


class GeoContentReview(CleanRoomTimestamp, Base):
    __tablename__ = "geo_content_reviews_v1"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    subject_type: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    review_type: Mapped[str] = mapped_column(String(40), nullable=False)
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    checks: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    issues: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)


class GeoDistributionRun(CleanRoomTimestamp, Base):
    __tablename__ = "geo_distribution_runs_v1"
    __table_args__ = (
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_geo_distribution_idempotency_v1"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    action_id: Mapped[int | None] = mapped_column(ForeignKey("geo_optimization_actions_v1.id"))
    content_asset_id: Mapped[int | None] = mapped_column(ForeignKey("geo_content_assets_v1.id"))
    requested_platforms: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="requested", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    requested_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)


class GeoDistributionTarget(CleanRoomTimestamp, Base):
    __tablename__ = "geo_distribution_targets_v1"

    id: Mapped[int] = mapped_column(primary_key=True)
    distribution_run_id: Mapped[int] = mapped_column(
        ForeignKey("geo_distribution_runs_v1.id"), nullable=False, index=True
    )
    platform_variant_id: Mapped[int | None] = mapped_column(ForeignKey("geo_platform_variants_v1.id"))
    platform_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    adapter_version: Mapped[str] = mapped_column(String(40), nullable=False, default="mcp-adapter.v1")
    request_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    draft_readback_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_started")
    candidate_draft_url: Mapped[str | None] = mapped_column(String(1500))
    draft_url: Mapped[str | None] = mapped_column(String(1500))
    external_draft_id: Mapped[str | None] = mapped_column(String(255))
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    response_artifact_uri: Mapped[str | None] = mapped_column(String(1500))
    readback_artifact_uri: Mapped[str | None] = mapped_column(String(1500))
    waiting_human_reason: Mapped[str | None] = mapped_column(Text)
    blocked_reason: Mapped[str | None] = mapped_column(Text)
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    final_action_clicked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class GeoReobservation(CleanRoomTimestamp, Base):
    __tablename__ = "geo_reobservations_v1"

    id: Mapped[int] = mapped_column(primary_key=True)
    action_id: Mapped[int] = mapped_column(
        ForeignKey("geo_optimization_actions_v1.id"), nullable=False, unique=True, index=True
    )
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    run_id: Mapped[int] = mapped_column(ForeignKey("geo_observation_runs_v1.id"), nullable=False)
    evidence_id: Mapped[int] = mapped_column(ForeignKey("geo_evidence_v1.id"), nullable=False)
    conclusion: Mapped[str] = mapped_column(Text, nullable=False)
    measured_delta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class GeoBrandFact(CleanRoomTimestamp, Base):
    __tablename__ = "geo_brand_facts_v1"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")


class GeoContentAudit(CleanRoomTimestamp, Base):
    __tablename__ = "geo_content_audits_v1"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    target_url: Mapped[str | None] = mapped_column(String(1000))
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    audit_version: Mapped[str] = mapped_column(String(80), nullable=False)
    score: Mapped[float] = mapped_column(nullable=False)
    checks: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class GeoBrowserAccount(CleanRoomTimestamp, Base):
    """Credential-free pointer to one isolated browser profile.

    The browser owns cookies and login state. This table stores only non-secret routing
    metadata, a one-way isolation fingerprint, health, and an opaque lease hash.
    """

    __tablename__ = "geo_browser_accounts_v1"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "provider_key", "alias", name="uq_geo_browser_account_alias_v1"
        ),
        UniqueConstraint(
            "provider_key", "ego_task_space_id", name="uq_geo_browser_account_task_space_v1"
        ),
        UniqueConstraint(
            "provider_key", "browser_profile_alias", name="uq_geo_browser_account_profile_v1"
        ),
        UniqueConstraint(
            "provider_key", "session_fingerprint", name="uq_geo_browser_account_fingerprint_v1"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    provider_key: Mapped[str] = mapped_column(
        String(40), nullable=False, default="deepseek", index=True
    )
    alias: Mapped[str] = mapped_column(String(80), nullable=False)
    ego_task_space_id: Mapped[int | None] = mapped_column(Integer)
    browser_profile_alias: Mapped[str | None] = mapped_column(String(120))
    session_fingerprint: Mapped[str | None] = mapped_column(String(64))
    isolation_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cohort: Mapped[str] = mapped_column(String(40), nullable=False, default="clean_baseline")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="onboarding", index=True
    )
    health_note: Mapped[str | None] = mapped_column(String(500))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_token_hash: Mapped[str | None] = mapped_column(String(64))
    lease_worker_id: Mapped[str | None] = mapped_column(String(120))
    lease_run_id: Mapped[int | None] = mapped_column(ForeignKey("geo_observation_runs_v1.id"))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def isolation_verified(self) -> bool:
        return bool(
            self.browser_profile_alias and self.session_fingerprint and self.isolation_verified_at
        )


class GeoSamplingBatch(CleanRoomTimestamp, Base):
    __tablename__ = "geo_sampling_batches_v1"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("geo_observation_runs_v1.id"), nullable=False, unique=True, index=True
    )
    observation_ledger_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("geo_observation_batches_v1.id"), unique=True, index=True
    )
    provider_key: Mapped[str] = mapped_column(String(40), nullable=False, default="deepseek")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    account_count: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    repeat_count: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    total_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=18)
    completed_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    current_message: Mapped[str | None] = mapped_column(String(500))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GeoSamplingSample(CleanRoomTimestamp, Base):
    __tablename__ = "geo_sampling_samples_v1"
    __table_args__ = (
        UniqueConstraint(
            "batch_id",
            "browser_account_id",
            "question_plan_id",
            "repeat_index",
            name="uq_geo_sampling_sample_matrix_v1",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("geo_sampling_batches_v1.id"), nullable=False, index=True
    )
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), nullable=False, index=True
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("geo_observation_runs_v1.id"), nullable=False, index=True
    )
    observation_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("geo_observation_tasks_v1.id"), unique=True, index=True
    )
    browser_account_id: Mapped[int] = mapped_column(
        ForeignKey("geo_browser_accounts_v1.id"), nullable=False, index=True
    )
    question_plan_id: Mapped[int] = mapped_column(
        ForeignKey("geo_question_plans_v1.id"), nullable=False, index=True
    )
    repeat_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evidence_id: Mapped[int | None] = mapped_column(ForeignKey("geo_evidence_v1.id"), unique=True)
    conversation_url: Mapped[str | None] = mapped_column(String(1500))
    raw_artifact_uri: Mapped[str | None] = mapped_column(String(1500))
    screenshot_uri: Mapped[str | None] = mapped_column(String(1500))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    conversation_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
