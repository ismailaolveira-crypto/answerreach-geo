from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class WorkspaceCreate(BaseModel):
    company_id: int
    slug: str = Field(pattern=r"^[a-z0-9-]{3,100}$")
    brand_name: str = Field(min_length=1, max_length=255)
    brand_aliases: list[str] = Field(default_factory=list)
    website_url: str | None = None


class WorkspaceRead(WorkspaceCreate):
    id: int
    status: str
    model_config = ConfigDict(from_attributes=True)


class WorkspaceUpdate(BaseModel):
    """The small, product-facing subset of workspace identity settings.

    These values are intentionally not account/profile settings: they are the
    identifiers used when archived answers are classified for this workspace.
    """

    brand_name: str = Field(min_length=1, max_length=255)
    brand_aliases: list[str] = Field(default_factory=list, max_length=20)
    website_url: str | None = Field(default=None, max_length=500)


class WorkspaceIntegrationRead(BaseModel):
    workspace_id: int
    deepseek_api_key_configured: bool = False
    article_sync_mcp_server_path: str | None = None
    article_sync_mcp_token_configured: bool = False
    deepseek_updated_at: datetime | None = None
    article_sync_mcp_updated_at: datetime | None = None


class WorkspaceIntegrationUpdate(BaseModel):
    deepseek_api_key: str | None = Field(default=None, max_length=500)
    article_sync_mcp_server_path: str | None = Field(default=None, max_length=1000)
    article_sync_mcp_token: str | None = Field(default=None, max_length=1000)


class WorkspaceIntegrationTestRequest(BaseModel):
    integration: Literal["deepseek", "article_sync_mcp"]


class QuestionPlanCreate(BaseModel):
    question_text: str = Field(min_length=4, max_length=500)
    journey_stage: Literal["awareness", "consideration", "decision", "retention"] = "consideration"
    role: Literal["ciso", "technical_lead", "procurement"] = "technical_lead"
    topic_tags: list[str] = Field(default_factory=list, max_length=8)
    importance: int = Field(default=3, ge=1, le=5)
    is_brand_query: bool = False
    source_type: str = Field(default="manual", min_length=1, max_length=50)
    source_evidence: dict = Field(default_factory=dict)
    source_reason: str | None = Field(default=None, max_length=2000)
    source_at: datetime | None = None
    template_variables: list[str] = Field(default_factory=list, max_length=8)


class QuestionPlanUpdate(BaseModel):
    question_text: str = Field(min_length=4, max_length=500)
    journey_stage: Literal["awareness", "consideration", "decision", "retention"] | None = None
    role: Literal["ciso", "technical_lead", "procurement"] | None = None
    topic_tags: list[str] | None = Field(default=None, max_length=8)
    importance: int | None = Field(default=None, ge=1, le=5)
    template_variables: list[str] | None = Field(default=None, max_length=8)


class QuestionPlanRead(QuestionPlanCreate):
    id: int
    workspace_id: int
    active: bool
    status: str = "active"
    version: int = 1
    cluster_id: str | None = None
    similar_question_id: int | None = None
    similarity: float | None = None
    approved_by: int | None = None
    approved_at: datetime | None = None
    rejected_reason: str | None = None
    source_at: datetime | None = None
    prompt_version: str = "v1"
    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def fill_legacy_defaults(cls, value):
        if isinstance(value, dict):
            data = dict(value)
        else:
            data = {name: getattr(value, name, None) for name in cls.model_fields}
        defaults = {
            "role": "technical_lead",
            "topic_tags": [],
            "source_type": "manual",
            "source_evidence": {},
            "template_variables": [],
            "status": "active",
            "version": 1,
        }
        for name, default in defaults.items():
            if data.get(name) is None:
                data[name] = default
        return data


class QuestionPlanAction(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class QuestionPlanMerge(BaseModel):
    target_question_id: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=2000)


class QuestionReviewRead(BaseModel):
    id: int
    workspace_id: int
    question_plan_id: int
    actor_user_id: int | None
    action: str
    from_status: str | None
    to_status: str | None
    note: str | None
    snapshot: dict
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class QuestionLibraryRead(BaseModel):
    workspace: WorkspaceRead
    questions: list[QuestionPlanRead]
    counts: dict[str, int]
    filters: dict[str, str | None]
    stages: list[str]
    roles: list[str]
    topics: list[str]


class YaoSourceItem(BaseModel):
    number: int | None = None
    source: str | None = None
    domain: str | None = None
    title: str | None = None
    date: str | None = None
    url: str | None = None
    summary: str | None = None


class YaoSampleImport(BaseModel):
    sample_id: str
    question: str
    repeat_index: int = Field(ge=1)
    ok: bool
    started_at: datetime | None = None
    finished_at: datetime | None = None
    raw_artifact_uri: str | None = None
    screenshot_uri: str | None = None
    sampling_environment: dict = Field(default_factory=dict)
    answer_text: str = ""
    references: list[YaoSourceItem] = Field(default_factory=list)
    brand_status: Literal[
        "absent", "mentioned", "shortlisted", "recommended", "cited", "negative"
    ] = "absent"
    brand_position: int | None = Field(default=None, ge=1)
    competitor_positions: list[dict] = Field(default_factory=list)


class YaoDatasetImport(BaseModel):
    platform: Literal["deepseek", "doubao", "kimi", "qianwen", "yuanbao"]
    sample_mode: Literal["browser_assisted", "authorized_api", "manual_import"]
    evidence_level: Literal["auditable", "partial"]
    prompt_version: str = "v1"
    browser_account_id: int | None = Field(default=None, ge=1)
    lease_token: str | None = Field(default=None, min_length=20, max_length=300)
    samples: list[YaoSampleImport] = Field(min_length=1)


class YaoDeepSeekDatasetImport(BaseModel):
    """Native stage-1 `deepseek-crawl.json` envelope from yao-deepseek-crawler."""

    dataset: dict
    artifact_base_uri: str | None = None
    prompt_version: str = "v1"
    target_run_id: int | None = Field(
        default=None,
        description="Attach samples to a previously created standard observation run instead of creating a standalone import run.",
    )
    browser_account_id: int | None = Field(default=None, ge=1)
    lease_token: str | None = Field(default=None, min_length=20, max_length=300)


class YaoDoubaoDatasetImport(YaoDeepSeekDatasetImport):
    """Native stage-1 `doubao-crawl.json` envelope from yao-doubao-crawler."""


class EvidenceRead(BaseModel):
    id: int
    workspace_id: int
    run_id: int
    question_plan_id: int
    model_key: str
    model_label: str
    prompt_version: str
    sample_mode: str
    evidence_level: str
    collection_method: str
    is_real_provider_evidence: bool
    brand_status: str
    brand_position: int | None
    competitor_positions: list[dict] = Field(default_factory=list)
    answer_text: str
    source_items: list[dict]
    sampling_environment: dict
    raw_artifact_uri: str | None
    screenshot_uri: str | None
    captured_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ActionEvidenceSummaryRead(BaseModel):
    id: int
    question_plan_id: int
    model_label: str
    is_real_provider_evidence: bool
    brand_status: str
    competitor_positions: list[dict] = Field(default_factory=list)
    source_items: list[dict] = Field(default_factory=list)


class QuestionAnalysisMetricRead(BaseModel):
    answer_count: int
    mention_count: int
    mention_rate: float
    candidate_count: int
    recommendation_count: int
    recommendation_rate: float
    cited_count: int
    brand_citation_rate: float
    answers_with_sources: int
    source_rate: float
    average_position: float | None
    position_observation_count: int


class QuestionAnalysisModelRead(QuestionAnalysisMetricRead):
    key: str
    label: str
    latest_captured_at: datetime | None = None
    evidence_ids: list[int] = Field(default_factory=list)


class QuestionAnalysisCompetitorRead(BaseModel):
    key: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    appearances: int
    appearance_rate: float
    candidate_count: int
    recommendation_count: int
    average_position: float | None
    top3_count: int
    top3_rate: float
    wins_over_brand: int
    comparable_answers: int
    evidence_ids: list[int] = Field(default_factory=list)
    is_baseline: bool = False


class QuestionAnalysisSourceRead(BaseModel):
    key: str
    domain: str
    url: str
    title: str
    appearance_count: int
    model_count: int
    favored_models: list[dict] = Field(default_factory=list)
    evidence_ids: list[int] = Field(default_factory=list)


class QuestionAnalysisEvidencePreviewRead(BaseModel):
    id: int
    run_id: int
    model_key: str
    model_label: str
    brand_status: str
    brand_position: int | None
    answer_preview: str
    source_count: int
    captured_at: datetime


class QuestionAnalysisPeriodRead(QuestionAnalysisMetricRead):
    label: str


class QuestionAnalysisRead(BaseModel):
    question: QuestionPlanRead
    scope: dict
    summary: QuestionAnalysisMetricRead
    comparison: dict
    models: list[QuestionAnalysisModelRead] = Field(default_factory=list)
    competitors: list[QuestionAnalysisCompetitorRead] = Field(default_factory=list)
    sources: list[QuestionAnalysisSourceRead] = Field(default_factory=list)
    trend: list[QuestionAnalysisPeriodRead] = Field(default_factory=list)
    evidence: list[QuestionAnalysisEvidencePreviewRead] = Field(default_factory=list)
    methodology: dict[str, str] = Field(default_factory=dict)


class ScorecardRead(BaseModel):
    id: int
    workspace_id: int
    run_id: int
    scoring_version: str
    input_fingerprint: str
    metrics: dict
    explanation: dict
    model_config = ConfigDict(from_attributes=True)


class DecisionMapCell(BaseModel):
    question_plan_id: int
    model_key: str
    model_label: str
    evidence: EvidenceRead | None = None


class DecisionMapRead(BaseModel):
    workspace: WorkspaceRead
    questions: list[QuestionPlanRead]
    scorecard: ScorecardRead | None = None
    models: list[dict]
    cells: list[DecisionMapCell]
    # These are calculated from the currently selected period/model/scope,
    # rather than copied from the last single-sample scorecard.
    metrics: dict = Field(default_factory=dict)
    metric_scope: dict = Field(default_factory=dict)
    sample_count: int = 0


class SourceMapBreakdown(BaseModel):
    key: str | None = None
    id: int | None = None
    label: str | None = None
    text: str | None = None
    citation_count: int
    answer_count: int


class SourceMapEvidenceReference(BaseModel):
    evidence_id: int
    source_url: str
    source_title: str | None = None


class SourceMapItem(BaseModel):
    key: str
    label: str
    canonical_url: str | None = None
    title: str | None = None
    citation_count: int
    answer_count: int
    model_count: int
    brand_absent_answer_count: int
    brand_absent_answer_ratio: float
    evidence_ids: list[int]
    evidence_references: list[SourceMapEvidenceReference]
    evidence_total: int
    evidence_truncated: bool
    models: list[SourceMapBreakdown]
    questions: list[SourceMapBreakdown]
    reason: str | None = None


class SourceMapSummary(BaseModel):
    answer_count: int
    answers_with_sources: int
    citation_count: int
    unique_domain_count: int
    unique_page_count: int
    brand_absent_answer_count: int
    brand_absent_answer_ratio: float
    ignored_source_count: int
    duplicate_source_count: int
    excluded_non_real_answer_count: int


class SourceMapRead(BaseModel):
    workspace: WorkspaceRead
    scope: dict
    summary: SourceMapSummary
    available_models: list[dict]
    available_questions: list[QuestionPlanRead]
    domains: list[SourceMapItem]
    pages: list[SourceMapItem]
    opportunities: list[SourceMapItem]
    interpretation_notice: str


class CompetitorEvidenceSnippet(BaseModel):
    evidence_id: int
    question_plan_id: int
    question: str
    model_key: str
    model_label: str
    brand_key: str
    brand_name: str
    matched_brand_keys: list[str]
    matched_aliases: list[str]
    match_count: int
    status: Literal["mentioned", "shortlisted", "recommended", "negative"]
    appearance_order: int
    explicit_list_position: int | None = None
    explicit_rank: int | None = None
    baseline_explicit_rank: int | None = None
    comparison_result: Literal["win", "comparable", "not_comparable"]
    win_reason_type: Literal["explicit_rank_ahead", "selected_baseline_absent"] | None = None
    context_snippet: str
    captured_at: datetime


class CompetitorBrandStat(BaseModel):
    key: str
    canonical_name: str
    aliases: list[str]
    is_baseline: bool
    hit_answer_count: int
    sample_answer_count: int
    mention_rate: float
    question_count: int
    model_count: int
    candidate_count: int
    recommendation_count: int
    negative_count: int
    average_first_appearance_order: float | None = None
    order_observation_count: int
    wins_over_baseline: int
    comparable_answers: int
    top3_count: int
    top3_rate: float
    explicit_average_position: float | None = None
    explicit_rank_observation_count: int
    win_reason_counts: dict[str, int]
    win_evidence: list[CompetitorEvidenceSnippet]
    evidence_total: int
    evidence: list[CompetitorEvidenceSnippet]


class CompetitorBreakdown(BaseModel):
    key: str | None = None
    id: int | None = None
    label: str
    answer_count: int
    brands: list[CompetitorBrandStat]


class CompetitorInsightRequest(BaseModel):
    period_days: int = Field(default=90, ge=1, le=3650)
    model_key: str | None = Field(default=None, min_length=1, max_length=120)
    question_plan_id: int | None = Field(default=None, ge=1)
    evidence_limit: int = Field(default=50, ge=1, le=100)


class CompetitorInsightFindingRead(BaseModel):
    title: str
    detail: str
    evidence_ids: list[int] = Field(default_factory=list)


class CompetitorInsightAnalysisRead(BaseModel):
    scope_summary: str
    overall_assessment: str
    findings: list[CompetitorInsightFindingRead]
    recommended_actions: list[str]
    limitations: list[str]


class CompetitorInsightRead(BaseModel):
    provider: str
    model: str
    generated_at: datetime
    scope: dict
    analysis: CompetitorInsightAnalysisRead
    snapshot_id: int | None = None
    persisted: bool = False
    is_stale: bool = False
    source_evidence_count: int = 0


class CompetitorComparisonSummary(BaseModel):
    answer_count: int
    tracked_brand_count: int
    answers_with_tracked_brand: int
    excluded_non_real_answer_count: int
    comparable_answer_count: int
    answers_where_competitor_wins: int


class CompetitorActionDiagnostic(BaseModel):
    competitor_key: str
    competitor_name: str
    model_key: str
    model_label: str
    question_plan_id: int
    question: str
    competitor_hit_count: int
    baseline_hit_count: int
    mention_gap: int
    wins_over_baseline: int
    comparable_answers: int
    reason_type: Literal["explicit_rank_ahead", "selected_baseline_absent"]
    reason_label: str
    evidence_count: int
    evidence_ids: list[int]
    evidence: list[CompetitorEvidenceSnippet]
    suggestion: str
    suggestion_type: Literal[
        "fill_citable_content_then_retest",
        "strengthen_comparison_evidence_then_retest",
    ]


class CompetitorComparisonRead(BaseModel):
    workspace: WorkspaceRead
    scope: dict
    summary: CompetitorComparisonSummary
    brands: list[CompetitorBrandStat]
    by_model: list[CompetitorBreakdown]
    by_question: list[CompetitorBreakdown]
    action_diagnostics: list[CompetitorActionDiagnostic]
    available_models: list[dict]
    available_questions: list[QuestionPlanRead]
    matching_rule_version: str
    methodology: dict[str, str]


class ObservationRunRead(BaseModel):
    id: int
    workspace_id: int
    adapter_key: str
    status: str
    request_context: dict
    started_at: datetime | None
    completed_at: datetime | None
    failure_reason: str | None
    model_config = ConfigDict(from_attributes=True)


class StandardObservationRequest(BaseModel):
    """The intentionally small public input for the normal decision-map CTA."""

    repeat_count: int = Field(default=3, ge=1, le=5)


class StandardObservationResponse(BaseModel):
    run: ObservationRunRead
    message: str
    providers: list[dict]
    question_count: int


class OfficialApiObservationRequest(BaseModel):
    """Run one real provider question and archive its search evidence."""

    question_plan_id: int = Field(ge=1)
    provider_id: int | None = Field(default=None, ge=1)
    repeat_index: int = Field(default=1, ge=1, le=5)
    repeat_count: int = Field(default=1, ge=1, le=5)
    observation_group_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,80}$")

    @model_validator(mode="after")
    def validate_repeat_window(self):
        if self.repeat_index > self.repeat_count:
            raise ValueError("repeat_index cannot exceed repeat_count")
        return self


class OfficialApiObservationResponse(BaseModel):
    run: ObservationRunRead
    evidence: EvidenceRead
    scorecard: ScorecardRead
    message: str


class QueuedOfficialApiObservationResponse(BaseModel):
    job_id: int
    status: Literal["pending", "running"]
    message: str


class OfficialApiObservationJobStatus(BaseModel):
    job_id: int
    status: Literal["pending", "running", "success", "failed"]
    run_id: int | None = None
    evidence_id: int | None = None
    error_message: str | None = None


class OfficialApiObservationBatchCreate(BaseModel):
    provider_ids: list[int] = Field(min_length=1, max_length=5)
    question_plan_ids: list[int] = Field(min_length=1, max_length=5)
    repeat_count: int = Field(default=1, ge=1, le=5)

    @model_validator(mode="after")
    def validate_unique_matrix(self):
        if len(set(self.provider_ids)) != len(self.provider_ids):
            raise ValueError("provider_ids must be unique")
        if len(set(self.question_plan_ids)) != len(self.question_plan_ids):
            raise ValueError("question_plan_ids must be unique")
        return self


class OfficialApiObservationBatchGroup(BaseModel):
    id: int
    key: str
    label: str
    total: int
    pending: int
    running: int
    succeeded: int
    failed: int


class OfficialApiObservationBatchSummary(BaseModel):
    batch_id: int
    source_type: str
    status: Literal["pending", "running", "success", "partial", "failed"]
    provider_count: int
    question_count: int
    repeat_count: int
    total: int
    pending: int
    running: int
    succeeded: int
    failed: int
    progress_percent: int
    status_percentages: dict[str, int] = Field(default_factory=dict)
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class OfficialApiObservationTaskRead(BaseModel):
    job_id: int
    provider_id: int
    provider_key: str
    provider_label: str
    question_plan_id: int
    question_label: str
    repeat_index: int
    status: Literal["pending", "running", "success", "failed"]
    evidence_id: int | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: int | None = None


class PaginationRead(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int


class OfficialApiObservationBatchRead(OfficialApiObservationBatchSummary):
    provider_groups: list[OfficialApiObservationBatchGroup]
    question_groups: list[OfficialApiObservationBatchGroup]
    evidence_ids: list[int] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    tasks: list[OfficialApiObservationTaskRead] = Field(default_factory=list)
    task_pagination: PaginationRead


class OfficialApiObservationBatchListRead(BaseModel):
    items: list[OfficialApiObservationBatchSummary]
    pagination: PaginationRead


class ObservationLedgerTaskRead(BaseModel):
    task_id: int
    batch_id: int
    source_type: str
    batch_status: str
    task_status: str
    provider_id: int | None = None
    provider_key: str
    provider_label: str
    model_key: str
    model_label: str
    question_plan_id: int
    question_text: str
    repeat_index: int
    repeat_count: int
    run_id: int | None = None
    evidence_id: int | None = None
    queue_job_id: int | None = None
    attempt_count: int
    error_code: str | None = None
    error_detail: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class ObservationLedgerListRead(BaseModel):
    items: list[ObservationLedgerTaskRead]
    pagination: PaginationRead


class BrowserAccountCreate(BaseModel):
    alias: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    ego_task_space_id: int | None = Field(default=None, ge=1)
    browser_profile_alias: str | None = Field(
        default=None, min_length=2, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    cohort: Literal["clean_baseline", "real_user"] = "clean_baseline"


class BrowserAccountUpdate(BaseModel):
    status: Literal["onboarding", "ready", "reauth_required", "disabled"]
    health_note: str | None = Field(default=None, max_length=500)
    cohort: Literal["clean_baseline", "real_user"] | None = None
    browser_profile_alias: str | None = Field(
        default=None, min_length=2, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    session_fingerprint: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$"
    )


class BrowserAccountRead(BaseModel):
    id: int
    workspace_id: int
    provider_key: Literal["deepseek"]
    alias: str
    ego_task_space_id: int | None
    browser_profile_alias: str | None
    cohort: str
    status: str
    isolation_verified: bool = False
    isolation_verified_at: datetime | None
    health_note: str | None
    last_checked_at: datetime | None
    last_used_at: datetime | None
    cooldown_until: datetime | None
    consecutive_failures: int
    lease_worker_id: str | None
    lease_run_id: int | None
    lease_expires_at: datetime | None
    model_config = ConfigDict(from_attributes=True)


class BrowserAccountLeaseRequest(BaseModel):
    worker_id: str = Field(min_length=2, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    run_id: int | None = Field(default=None, ge=1)
    lease_seconds: int = Field(default=600, ge=60, le=1800)


class BrowserAccountLeaseRead(BaseModel):
    account: BrowserAccountRead
    lease_token: str


class BrowserAccountReleaseRequest(BaseModel):
    lease_token: str = Field(min_length=20, max_length=300)
    outcome: Literal["success", "rate_limited", "auth_expired", "error"]
    health_note: str | None = Field(default=None, max_length=500)
    cooldown_seconds: int | None = Field(default=None, ge=60, le=86400)


class SamplingBatchCreate(BaseModel):
    account_count: Literal[2] = 2
    question_count: Literal[3] = 3
    repeat_count: Literal[3] = 3


class SamplingSampleRead(BaseModel):
    id: int
    batch_id: int
    browser_account_id: int
    question_plan_id: int
    repeat_index: int
    status: str
    attempt_count: int
    evidence_id: int | None
    conversation_url: str | None
    error_code: str | None
    error_detail: str | None
    started_at: datetime | None
    completed_at: datetime | None
    conversation_deleted_at: datetime | None
    model_config = ConfigDict(from_attributes=True)


class SamplingBatchRead(BaseModel):
    id: int
    workspace_id: int
    run_id: int
    provider_key: str
    status: str
    account_count: int
    question_count: int
    repeat_count: int
    total_samples: int
    completed_samples: int
    failed_samples: int
    configuration: dict
    current_message: str | None
    failure_reason: str | None
    started_at: datetime | None
    completed_at: datetime | None
    samples: list[SamplingSampleRead] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


class SamplingWorkerClaimRequest(BaseModel):
    worker_id: str = Field(min_length=2, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    lease_seconds: int = Field(default=900, ge=60, le=1800)


class SamplingWorkerClaimRead(BaseModel):
    sample_id: int
    batch_id: int
    run_id: int
    account_id: int
    account_alias: str
    browser_profile_alias: str
    cohort: str
    brand_name: str
    brand_aliases: list[str]
    question_plan_id: int
    question: str
    repeat_index: int
    lease_token: str


class SamplingWorkerComplete(BaseModel):
    lease_token: str = Field(min_length=20, max_length=300)
    answer_text: str = Field(min_length=1)
    references: list[YaoSourceItem] = Field(default_factory=list)
    brand_status: Literal[
        "absent", "mentioned", "shortlisted", "recommended", "cited", "negative"
    ] = "absent"
    brand_position: int | None = Field(default=None, ge=1)
    competitor_positions: list[dict] = Field(default_factory=list)
    conversation_url: str = Field(min_length=10, max_length=1500)
    raw_artifact_uri: str = Field(min_length=5, max_length=1500)
    screenshot_uri: str = Field(min_length=5, max_length=1500)
    captured_at: datetime
    conversation_deleted_at: datetime
    sampling_environment: dict = Field(default_factory=dict)


class SamplingWorkerFail(BaseModel):
    lease_token: str = Field(min_length=20, max_length=300)
    error_code: str = Field(min_length=2, max_length=80)
    error_detail: str = Field(min_length=2, max_length=2000)
    outcome: Literal["retryable", "rate_limited", "auth_expired", "fatal"] = "retryable"


class ContentAuditCreate(BaseModel):
    title: str = ""
    body: str = Field(min_length=1)
    source_urls: list[str] = Field(default_factory=list)
    target_url: str | None = None


class ContentAuditRead(BaseModel):
    id: int
    workspace_id: int
    target_url: str | None
    content_fingerprint: str
    audit_version: str
    score: float
    checks: dict
    model_config = ConfigDict(from_attributes=True)


class WebsiteAuditRead(BaseModel):
    id: int
    workspace_id: int
    requested_url: str
    final_url: str | None = None
    status: Literal["ready", "needs_work", "blocked"]
    status_code: int | None = None
    content_type: str | None = None
    title: str | None = None
    meta_description: str | None = None
    canonical_url: str | None = None
    score: float
    audit_version: str
    checks: dict = Field(default_factory=dict)
    findings: list[dict] = Field(default_factory=list)
    response_headers: dict = Field(default_factory=dict)
    raw_html_sha256: str | None = None
    raw_html_size: int = 0
    artifact_manifest: list[dict] = Field(default_factory=list)
    response_ms: int | None = None
    checked_at: datetime
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class WebsiteAuditOverviewRead(BaseModel):
    website_url: str | None = None
    latest: WebsiteAuditRead | None = None


class ActionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    rationale: str = Field(min_length=1)
    hypothesis: str | None = None
    priority: Literal["high", "medium", "low"] = "medium"
    question_plan_id: int | None = None
    source_evidence_id: int | None = None
    opportunity_id: int | None = None


class ActionUpdate(BaseModel):
    status: Literal["proposed", "in_progress", "verified", "closed"] | None = None


class ActionRead(ActionCreate):
    id: int
    workspace_id: int
    status: str
    stage: str = "selected"
    baseline_snapshot: dict = Field(default_factory=dict)
    selected_scope: dict = Field(default_factory=dict)
    blocked_reason: str | None = None
    selected_at: datetime | None = None
    completed_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)


class ReobservationCreate(BaseModel):
    run_id: int
    evidence_id: int
    conclusion: str = Field(min_length=1)
    measured_delta: dict = Field(default_factory=dict)


class ActionOpportunityEvidenceRead(BaseModel):
    id: int
    opportunity_id: int
    evidence_id: int
    question_plan_id: int
    batch_id: int | None
    observation_task_id: int | None
    model_key: str
    signal_type: str
    signal_value: dict = Field(default_factory=dict)
    evidence_hash: str
    source_url: str | None
    model_config = ConfigDict(from_attributes=True)


class ActionOpportunityRead(BaseModel):
    id: int
    workspace_id: int
    fingerprint: str
    opportunity_type: str
    title: str
    summary: str
    priority_score: float
    priority_label: str
    evidence_strength: float
    source_gap_type: str | None
    recommended_asset_type: str
    recommended_platforms: list[str] = Field(default_factory=list)
    scope_snapshot: dict = Field(default_factory=dict)
    rule_version: str
    status: str
    first_seen_batch_id: int | None
    latest_seen_batch_id: int | None
    evidence: list[ActionOpportunityEvidenceRead] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


class ActionOpportunityDiscoverRequest(BaseModel):
    batch_id: int | None = Field(default=None, ge=1)
    question_plan_ids: list[int] = Field(default_factory=list, max_length=100)
    model_keys: list[str] = Field(default_factory=list, max_length=20)
    max_items: int = Field(default=50, ge=1, le=100)


class ActionOpportunityScopeBatchRead(BaseModel):
    id: int
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    eligible_evidence_count: int
    model_keys: list[str] = Field(default_factory=list)
    question_plan_ids: list[int] = Field(default_factory=list)


class ActionOpportunityScopeRead(BaseModel):
    latest_batch_id: int | None = None
    batches: list[ActionOpportunityScopeBatchRead] = Field(default_factory=list)
    models: list[dict] = Field(default_factory=list)
    questions: list[dict] = Field(default_factory=list)
    evidence_gate: str


class ActionStageUpdate(BaseModel):
    stage: Literal[
        "selected",
        "brief_ready",
        "generating",
        "draft_ready",
        "reviewing",
        "sync_requested",
        "awaiting_readback",
        "verified",
        "blocked",
        "closed",
    ]
    note: str | None = Field(default=None, max_length=2000)


class ActionEventRead(BaseModel):
    id: int
    workspace_id: int
    action_id: int | None
    event_type: str
    from_stage: str | None
    to_stage: str | None
    actor_type: str
    actor_user_id: int | None
    job_id: int | None
    detail: dict = Field(default_factory=dict)
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class AgentRuntimeRead(BaseModel):
    runtime_key: str = "local_codex"
    sdk_installed: bool
    sdk_version: str | None = None
    runtime_version: str | None = None
    ready: bool
    login_status: str
    default_model: str | None = None
    available_models: list[str] = Field(default_factory=list)
    active_run_count: int = 0
    max_concurrent_runs: int = 1
    capacity_available: bool = True
    run_timeout_seconds: int = 900
    error: str | None = None


class AgentRuntimeTestRead(BaseModel):
    ok: bool
    runtime: AgentRuntimeRead
    latency_ms: int
    thread_id: str | None = None
    error: str | None = None


class AgentRunCreate(BaseModel):
    selected_platforms: list[Literal["official_site", "zhihu", "wechat", "xiaohongshu"]] = Field(
        default_factory=list, max_length=4
    )
    model: str | None = Field(default=None, max_length=120)


class AgentRunRead(BaseModel):
    id: int
    workspace_id: int
    action_id: int
    job_id: int | None
    requested_by_user_id: int | None
    runtime_key: str
    model: str | None
    codex_thread_id: str | None
    codex_turn_id: str | None
    status: str
    stage: str
    selected_platforms: list[str] = Field(default_factory=list)
    result_snapshot: dict = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    cancel_requested_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class AgentEventRead(BaseModel):
    id: int
    workspace_id: int
    agent_run_id: int
    sequence: int
    event_type: str
    stage: str
    message: str
    detail: dict = Field(default_factory=dict)
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class AgentArtifactRead(BaseModel):
    id: int
    workspace_id: int
    agent_run_id: int
    artifact_kind: str
    uri: str
    sha256: str
    size_bytes: int
    metadata_json: dict = Field(default_factory=dict)
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class AgentProgressStageRead(BaseModel):
    key: Literal[
        "preparing_context",
        "researching_platform",
        "researching_brand",
        "adapting_platforms",
        "awaiting_review",
    ]
    label: str
    state: Literal["waiting", "running", "done", "waiting_human", "failed"]
    message: str | None = None
    event_sequence: int | None = None
    updated_at: datetime | None = None


class AgentProgressArtifactRead(BaseModel):
    """Safe artifact metadata for the product UI; local file paths stay private."""

    id: int
    artifact_kind: str
    sha256: str
    size_bytes: int
    created_at: datetime


class AgentRunProgressRead(BaseModel):
    run: AgentRunRead
    stages: list[AgentProgressStageRead]
    attempt_number: int = Field(ge=1)
    attempt_event_count: int = Field(ge=0)
    attempt_started_at: datetime | None = None
    progress_percent: int = Field(ge=0, le=100)
    elapsed_seconds: int = Field(ge=0)
    timeout_seconds: int = Field(ge=60)
    timeout_remaining_seconds: int | None = Field(default=None, ge=0)
    event_count: int = Field(ge=0)
    events: list[AgentEventRead] = Field(default_factory=list)
    artifacts: list[AgentProgressArtifactRead] = Field(default_factory=list)


class ContentBriefCreate(BaseModel):
    audience: str | None = Field(default=None, max_length=160)
    intent: str | None = Field(default=None, max_length=80)
    asset_type: Literal["article", "faq", "case_study", "comparison"] = "article"
    required_sections: list[str] = Field(default_factory=list, max_length=20)
    brand_fact_ids: list[int] = Field(default_factory=list, max_length=50)
    forbidden_claims: list[str] = Field(default_factory=list, max_length=30)
    open_questions: list[str] = Field(default_factory=list, max_length=30)


class ContentBriefRead(ContentBriefCreate):
    id: int
    workspace_id: int
    action_id: int
    question_plan_id: int | None
    audience: str
    intent: str
    required_sections: list[str]
    brand_fact_ids: list[int]
    evidence_ids: list[int]
    source_urls: list[str]
    required_claims: list[str]
    forbidden_claims: list[str]
    open_questions: list[str]
    prompt_template_id: int | None
    input_fingerprint: str
    status: str
    model_config = ConfigDict(from_attributes=True)


class ContentGenerateRequest(BaseModel):
    provider_id: int = Field(ge=1)
    platform_key: Literal["official_site", "zhihu", "wechat", "xiaohongshu"] = "official_site"


class ContentAssetRead(BaseModel):
    id: int
    workspace_id: int
    brief_id: int
    version: int
    title: str
    summary: str
    body_markdown: str
    content_fingerprint: str
    model_provider_id: int | None
    model_name: str | None
    prompt_template_id: int | None
    prompt_hash: str | None
    raw_artifact_uri: str | None
    generation_usage: dict = Field(default_factory=dict)
    status: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PlatformVariantCreate(BaseModel):
    platform_keys: list[Literal["official_site", "zhihu", "wechat", "xiaohongshu"]] = Field(
        default_factory=lambda: ["official_site", "zhihu", "wechat"]
    )


class PlatformVariantRead(BaseModel):
    id: int
    workspace_id: int
    content_asset_id: int
    platform_key: str
    version: int
    policy_version: str
    title: str
    summary: str
    body_markdown: str
    tags: list[str] = Field(default_factory=list)
    category: str | None
    image_manifest: list[dict] = Field(default_factory=list)
    adaptation_contract: dict = Field(default_factory=dict)
    content_fingerprint: str
    prompt_template_id: int | None
    prompt_hash: str | None
    status: str
    model_config = ConfigDict(from_attributes=True)


class ContentClaimRead(BaseModel):
    id: int
    content_asset_id: int
    claim_key: str
    claim_text: str
    support_type: str
    support_id: int | None
    source_url: str | None
    verification_status: str
    introduced_by_model: bool
    review_note: str | None
    model_config = ConfigDict(from_attributes=True)


class ContentReviewRead(BaseModel):
    id: int
    workspace_id: int
    subject_type: str
    subject_id: int
    review_type: str
    verdict: str
    checks: dict = Field(default_factory=dict)
    issues: list[dict] = Field(default_factory=list)
    reviewer_id: int | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ContentReviewPackageRead(BaseModel):
    asset: ContentAssetRead
    claims: list[ContentClaimRead] = Field(default_factory=list)
    variants: list[PlatformVariantRead] = Field(default_factory=list)
    reviews: list[ContentReviewRead] = Field(default_factory=list)
    pending_claim_count: int = 0
    approved_platform_keys: list[str] = Field(default_factory=list)
    requires_sourced_brand_facts: bool = False
    available_sourced_brand_fact_count: int = Field(default=0, ge=0)
    sourced_brand_fact_count: int = Field(default=0, ge=0)
    sourced_brand_fact_ids: list[int] = Field(default_factory=list)


class ContentReviewDecision(BaseModel):
    verdict: Literal["approved", "changes_requested"]
    confirmed_claim_ids: list[int] = Field(default_factory=list, max_length=200)
    unverified_claim_ids: list[int] = Field(default_factory=list, max_length=200)
    platform_keys: list[Literal["official_site", "zhihu", "wechat", "xiaohongshu"]] = Field(
        default_factory=list, max_length=4
    )
    reviewed_platform_keys: list[
        Literal["official_site", "zhihu", "wechat", "xiaohongshu"]
    ] = Field(default_factory=list, max_length=4)
    note: str | None = Field(default=None, max_length=2000)


class AgentRevisionRequest(BaseModel):
    content_asset_id: int = Field(ge=1)


class DistributionRunCreate(BaseModel):
    content_asset_id: int = Field(ge=1)
    platform_keys: list[Literal["official_site", "zhihu", "wechat", "xiaohongshu"]] = Field(min_length=1)
    idempotency_key: str = Field(min_length=8, max_length=160)


class DistributionTargetRead(BaseModel):
    id: int
    distribution_run_id: int
    platform_variant_id: int | None
    platform_key: str
    adapter_version: str
    request_status: str
    draft_readback_status: str
    candidate_draft_url: str | None
    draft_url: str | None
    external_draft_id: str | None
    response_artifact_uri: str | None
    readback_artifact_uri: str | None
    waiting_human_reason: str | None
    blocked_reason: str | None
    last_error_code: str | None
    final_action_clicked: bool
    human_publish_status: str = "not_ready"
    public_url: str | None = None
    publication_verification_status: str = "not_checked"
    published_at: datetime | None = None
    published_by_user_id: int | None = None
    model_config = ConfigDict(from_attributes=True)


class DistributionRunRead(BaseModel):
    id: int
    workspace_id: int
    action_id: int | None
    content_asset_id: int | None
    requested_platforms: list[str]
    stage: str
    idempotency_key: str
    status: str
    targets: list[DistributionTargetRead] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


class ContentLibraryItemRead(BaseModel):
    asset: ContentAssetRead
    action_id: int
    action_title: str
    action_stage: str
    question_plan_id: int | None
    variants: list[PlatformVariantRead] = Field(default_factory=list)
    pending_claim_count: int = 0
    available_sourced_brand_fact_count: int = Field(default=0, ge=0)
    sourced_brand_fact_count: int = Field(default=0, ge=0)
    brand_fact_snapshot_stale: bool = False
    approved_platform_keys: list[str] = Field(default_factory=list)
    latest_review_verdict: str | None = None
    latest_review_note: str | None = None
    agent_run_id: int | None = None
    agent_run_status: str | None = None
    distribution_run_id: int | None = None
    distribution_status: str | None = None
    saved_draft_count: int = 0
    total_draft_targets: int = 0
    draft_targets: list[DistributionTargetRead] = Field(default_factory=list)
    is_latest_version: bool = True
    latest_version_id: int
    latest_version_number: int = Field(ge=1)


class DistributionClientTargetResult(BaseModel):
    platform_key: str = Field(min_length=1, max_length=80)
    request_status: Literal["draft_saved", "failed", "cancelled"]
    draft_url: str | None = Field(default=None, max_length=1500)
    external_draft_id: str | None = Field(default=None, max_length=255)
    message: str | None = Field(default=None, max_length=2000)


class DistributionClientResults(BaseModel):
    targets: list[DistributionClientTargetResult] = Field(min_length=1, max_length=20)


class HumanPublicationRecord(BaseModel):
    public_url: str = Field(min_length=8, max_length=1500)


class ActionRetestRead(BaseModel):
    id: int
    action_id: int
    workspace_id: int
    status: str
    baseline_batch_id: int | None = None
    retest_batch_id: int | None = None
    retest_queue_job_id: int | None = None
    scope_snapshot: dict = Field(default_factory=dict)
    baseline_metrics: dict = Field(default_factory=dict)
    retest_metrics: dict = Field(default_factory=dict)
    conclusion: str = "pending"
    measured_delta: dict = Field(default_factory=dict)
    batch: OfficialApiObservationBatchSummary | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ActionWorkbenchStateRead(BaseModel):
    agent_runs: list[AgentRunRead] = Field(default_factory=list)
    review_packages: list[ContentReviewPackageRead] = Field(default_factory=list)
    distribution_runs: list[DistributionRunRead] = Field(default_factory=list)
    retests: list[ActionRetestRead] = Field(default_factory=list)


class PromptTemplateRead(BaseModel):
    id: int
    prompt_key: str
    version: str
    purpose: str
    platform_key: str | None
    checksum: str
    status: str
    model_config = ConfigDict(from_attributes=True)


class BrandFactCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    statement: str = Field(min_length=1)
    source_url: str | None = Field(default=None, max_length=1000)

    @field_validator("title", "statement")
    @classmethod
    def normalize_required_text(cls, value: str):
        normalized = value.strip()
        if not normalized:
            raise ValueError("brand fact text cannot be blank")
        return normalized

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None):
        if value is None:
            return None
        normalized = value.strip()
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source_url must be a public http or https URL")
        return normalized


class BrandFactUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    statement: str | None = Field(default=None, min_length=1)
    source_url: str | None = Field(default=None, max_length=1000)
    status: Literal["active", "inactive"] | None = None

    @field_validator("title", "statement")
    @classmethod
    def normalize_optional_text(cls, value: str | None):
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("brand fact text cannot be blank")
        return normalized

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None):
        if value is None:
            return None
        normalized = value.strip()
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source_url must be a public http or https URL")
        return normalized

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("At least one brand fact field must be provided")
        for field_name in ("title", "statement", "status"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class BrandFactRead(BrandFactCreate):
    id: int
    workspace_id: int
    status: str
    model_config = ConfigDict(from_attributes=True)
