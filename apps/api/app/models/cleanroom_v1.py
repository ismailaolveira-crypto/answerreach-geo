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
