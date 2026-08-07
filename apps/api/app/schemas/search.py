from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.schemas.common import TimestampedSchema


class LLMProviderBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    provider_type: str = Field(default="mock", max_length=100)
    api_base_url: str | None = None
    model_name: str = Field(default="mock-geo-search", max_length=255)
    auth_config: dict[str, Any] = Field(default_factory=dict)
    cost_rule: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"


class LLMProviderCreate(LLMProviderBase):
    pass


class LLMProviderUpdate(BaseModel):
    name: str | None = None
    provider_type: str | None = None
    api_base_url: str | None = None
    model_name: str | None = None
    auth_config: dict[str, Any] | None = None
    cost_rule: dict[str, Any] | None = None
    status: str | None = None


class LLMProviderRead(LLMProviderBase, TimestampedSchema):
    id: int

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("auth_config")
    def serialize_auth_config(self, value: dict[str, Any]) -> dict[str, Any]:
        masked = dict(value or {})
        if masked.get("api_key"):
            masked["api_key"] = "***configured***"
            masked["api_key_configured"] = True
        if masked.get("api_key_encrypted"):
            masked.pop("api_key_encrypted", None)
            masked["api_key_configured"] = True
        return masked


class LLMProviderTestRequest(BaseModel):
    prompt_text: str = "网络安全培训公司哪家好？"
    company_name: str = "示例企业"
    industry: str = "网络安全"


class LLMProviderTestResult(BaseModel):
    id: int | None = None
    provider_id: int
    actor_user_id: int | None = None
    ok: bool
    prompt_text: str
    company_name: str | None = None
    industry: str | None = None
    answer_summary: str | None = None
    raw_answer_preview: str | None = None
    error_message: str | None = None
    latency_ms: int | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class LLMProviderCollectionSummary(BaseModel):
    provider_id: int
    collection_ready: bool = False
    collection_blocker: str | None = None
    diagnostic_ready: bool = False
    latest_test_ok: bool | None = None
    latest_test_error: str | None = None
    latest_test_created_at: datetime | None = None
    total_task_count: int = 0
    success_task_count: int = 0
    failed_task_count: int = 0
    result_count: int = 0
    usage_record_count: int = 0
    total_tokens: int = 0
    latest_task_id: int | None = None
    latest_task_project_id: int | None = None
    latest_task_type: str | None = None
    latest_task_status: str | None = None
    latest_task_started_at: datetime | None = None
    latest_task_finished_at: datetime | None = None
    latest_task_error_message: str | None = None
    latest_result_id: int | None = None
    latest_result_project_id: int | None = None
    latest_result_collected_at: datetime | None = None


class LLMProviderDiagnostic(BaseModel):
    provider_id: int
    provider_type: str
    ready: bool
    auth_ready: bool
    auth_source: str
    base_url: str | None = None
    endpoint_path: str
    supports_web_search: bool
    access_method: str
    search_mode: str
    search_access_status: str
    setup_steps: list[str] = Field(default_factory=list)
    last_blocker: str | None = None
    missing: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class LLMProviderReadiness(BaseModel):
    provider_id: int
    diagnostic: LLMProviderDiagnostic
    latest_test: LLMProviderTestResult | None = None
    test_fresh: bool = False
    collection_ready: bool = False
    collection_blocker: str | None = None


class LLMProviderOnboardingItem(BaseModel):
    provider_type: str
    platform_key: str | None = None
    label: str
    default_base_url: str | None = None
    template_name: str
    template_base_url: str | None = None
    template_model_name: str
    model_examples: list[str] = Field(default_factory=list)
    auth_env: str | None = None
    access_method: str
    search_mode: str
    supports_web_search: bool
    collection_fit: str
    setup_steps: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class CrawlTaskCreate(BaseModel):
    task_type: str = "manual_batch"
    schedule_type: str = "manual"
    provider_ids: list[int] = Field(default_factory=list)
    target_question_ids: list[int] = Field(default_factory=list)
    keyword_ids: list[int] = Field(default_factory=list)
    sample_runs_per_prompt: int = Field(default=1, ge=1, le=20)
    execute_now: bool = True
    max_estimated_cost: float | None = Field(default=None, ge=0)
    allow_over_budget: bool = False


class CrawlTaskRead(TimestampedSchema):
    id: int
    project_id: int
    task_type: str
    schedule_type: str
    provider_ids: list[int]
    target_question_ids: list[int]
    keyword_ids: list[int]
    sample_runs_per_prompt: int = 1
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None

    model_config = ConfigDict(from_attributes=True)


class CrawlTaskEstimateProvider(BaseModel):
    id: int
    name: str
    provider_type: str
    is_real: bool
    collection_ready: bool
    cost_configured: bool = False
    estimated_cost: float = 0
    currency: str = "USD"


class CrawlTaskEstimateRead(BaseModel):
    provider_count: int
    real_provider_count: int
    target_question_count: int
    keyword_count: int
    prompt_count: int
    total_call_count: int
    estimated_prompt_tokens: int = 0
    estimated_completion_tokens: int = 0
    estimated_total_tokens: int = 0
    estimated_cost: float = 0
    currency: str = "USD"
    cost_configured_provider_count: int = 0
    scope_mode: str
    providers: list[CrawlTaskEstimateProvider]
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CrawlScheduleCreate(BaseModel):
    name: str = Field(default="Hourly GEO monitor", min_length=1, max_length=255)
    schedule_type: str = "hourly"
    interval_hours: int = Field(default=1, ge=1, le=24 * 30)
    provider_ids: list[int] = Field(default_factory=list)
    target_question_ids: list[int] = Field(default_factory=list)
    keyword_ids: list[int] = Field(default_factory=list)
    sample_runs_per_prompt: int = Field(default=1, ge=1, le=20)
    status: str = "active"
    execute_now: bool = False


class CrawlScheduleUpdate(BaseModel):
    name: str | None = None
    schedule_type: str | None = None
    interval_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    provider_ids: list[int] | None = None
    target_question_ids: list[int] | None = None
    keyword_ids: list[int] | None = None
    sample_runs_per_prompt: int | None = Field(default=None, ge=1, le=20)
    status: str | None = None


class CrawlScheduleRead(TimestampedSchema):
    id: int
    project_id: int
    name: str
    schedule_type: str
    interval_hours: int
    provider_ids: list[int]
    target_question_ids: list[int]
    keyword_ids: list[int]
    sample_runs_per_prompt: int = 1
    status: str
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    last_created_task_id: int | None = None

    model_config = ConfigDict(from_attributes=True)


class CrawlScheduleRunResult(BaseModel):
    checked_at: datetime
    due_schedule_count: int
    task_ids: list[int]


class QueueJobRead(TimestampedSchema):
    id: int
    job_type: str
    status: str
    priority: int
    payload_json: dict[str, Any]
    attempts: int
    max_attempts: int
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None

    model_config = ConfigDict(from_attributes=True)


class QueueJobSummary(BaseModel):
    total: int = 0
    pending: int = 0
    running: int = 0
    success: int = 0
    failed: int = 0


class QueueJobListResponse(BaseModel):
    summary: QueueJobSummary
    jobs: list[QueueJobRead]


class QueueJobRunResult(BaseModel):
    ran: bool
    job: QueueJobRead | None = None
    message: str


class QueueReadyRunResult(BaseModel):
    checked_at: datetime
    created_task_ids: list[int] = Field(default_factory=list)
    ran_job_ids: list[int] = Field(default_factory=list)
    ran_job_count: int = 0
    success_job_count: int = 0
    failed_job_count: int = 0
    pending_job_count: int = 0
    message: str


class CrawlTaskLogRead(TimestampedSchema):
    id: int
    task_id: int
    project_id: int
    level: str
    message: str
    detail_json: dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class CrawlResultRead(TimestampedSchema):
    id: int
    task_id: int
    project_id: int
    target_question_id: int | None = None
    keyword_id: int | None = None
    provider_id: int | None = None
    prompt_text: str
    raw_answer: str
    answer_summary: str | None = None
    status: str
    collected_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class AnswerAnalysisRead(TimestampedSchema):
    id: int
    crawl_result_id: int
    company_mentioned: bool
    company_recommended: bool
    company_rank: int | None = None
    sentiment: str
    confidence: int
    analysis_json: dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class AnswerAnalysisUpdate(BaseModel):
    company_mentioned: bool | None = None
    company_recommended: bool | None = None
    company_rank: int | None = Field(default=None, ge=1, le=100)
    sentiment: str | None = Field(default=None, pattern="^(positive|neutral|negative)$")
    confidence: int | None = Field(default=None, ge=0, le=100)
    correction_note: str | None = None


class CrawlResultDetail(CrawlResultRead):
    analysis: AnswerAnalysisRead | None = None
    mentioned_entities: list[dict[str, Any]] = Field(default_factory=list)
    citation_sources: list[dict[str, Any]] = Field(default_factory=list)


class BrowserObservationCreate(BaseModel):
    provider_id: int | None = None
    report_id: int | None = None
    target_question_id: int | None = None
    keyword_id: int | None = None
    platform_name: str | None = None
    prompt_text: str = Field(min_length=1, max_length=4000)
    raw_answer: str = Field(min_length=1)
    answer_summary: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    screenshot_url: str | None = None
    observation_url: str | None = None
    observer_name: str | None = None
    note: str | None = None


class BrowserObservationBulkCreate(BaseModel):
    observations: list[BrowserObservationCreate] = Field(min_length=1, max_length=20)


class BrowserObservationBulkRead(BaseModel):
    created_count: int
    result_ids: list[int]
    source_count: int
    screenshot_evidence_count: int
    results: list["CrawlResultDetail"]


class BrowserObservationRead(CrawlResultRead):
    report_id: int | None = None
    platform_name: str | None = None
    observation_url: str | None = None
    screenshot_url: str | None = None
    observer_name: str | None = None
    note: str | None = None
    source_count: int = 0
    screenshot_evidence_count: int = 0


class ProjectSearchMetrics(BaseModel):
    project_id: int
    total_answers: int
    company_mentions: int
    company_recommendations: int
    competitor_mentions: int
    company_mention_rate: float
    company_recommendation_rate: float
    competitor_mention_rate: float
    top_competitors: list[dict[str, Any]]
    provider_breakdown: list[dict[str, Any]]


class ProjectSourceInsight(BaseModel):
    source_domain: str | None
    source_url: str | None
    source_type: str
    appearances: int
    is_owned: bool
    is_placed: bool
    has_content_asset: bool
    placement_count: int = 0
    published_placement_count: int = 0
    latest_placement_at: datetime | None = None
    placement_frequency_label: str = "未投放"
    ai_readiness_status: str = "unknown"
    crawlability_status: str = "unknown"
    crawlable_score: int
    ai_readiness_score: int


class ProjectSourceDetail(BaseModel):
    insight: ProjectSourceInsight
    evidence_results: list[dict[str, Any]]
    matching_content_assets: list[dict[str, Any]]
    matching_placements: list[dict[str, Any]]
    recommendations: list[str]
