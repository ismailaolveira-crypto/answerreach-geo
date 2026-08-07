from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import TimestampedSchema


class ProjectBase(BaseModel):
    company_id: int
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    target_industry: str | None = None
    target_audience: str | None = None
    status: str = "active"


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    company_id: int | None = None
    name: str | None = None
    description: str | None = None
    target_industry: str | None = None
    target_audience: str | None = None
    status: str | None = None


class ProjectRead(ProjectBase, TimestampedSchema):
    id: int

    model_config = ConfigDict(from_attributes=True)


class ProjectInputReadinessCheck(BaseModel):
    key: str
    label: str
    current: int
    required: int
    ok: bool
    help_text: str


class ProjectDetail(ProjectRead):
    target_question_count: int = 0
    keyword_count: int = 0
    competitor_count: int = 0
    content_asset_count: int = 0
    placement_count: int = 0
    diagnostic_readiness_score: int = 0
    diagnostic_readiness_status: str = "not_ready"
    diagnostic_readiness_checks: list[ProjectInputReadinessCheck] = []


class ProjectStageGoalBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    metric_key: str = Field(min_length=1, max_length=100)
    target_value: float
    baseline_value: float = 0
    due_at: datetime | None = None
    owner: str | None = None
    status: str = "active"
    note: str | None = None


class ProjectStageGoalCreate(ProjectStageGoalBase):
    pass


class ProjectStageGoalUpdate(BaseModel):
    title: str | None = None
    metric_key: str | None = None
    target_value: float | None = None
    baseline_value: float | None = None
    due_at: datetime | None = None
    owner: str | None = None
    status: str | None = None
    note: str | None = None


class ProjectStageGoalRead(ProjectStageGoalBase, TimestampedSchema):
    id: int
    project_id: int
    current_value: float = 0
    progress_rate: float = 0
    remaining_value: float = 0
    risk_level: str = "unknown"
    review_summary: str | None = None
    recommendations: list[str] = []
    suggested_actions: list[dict[str, str]] = []
    due_days_remaining: int | None = None
    active_alert_type: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ProjectOperatingTrendPoint(BaseModel):
    date: str
    maturity_score: int
    health_score: int
    answer_count: int
    browser_observation_count: int
    recommendation_rate: float
    approved_content_count: int
    published_placement_count: int
    accepted_delivery_count: int


class ProjectOperatingTrends(BaseModel):
    project_id: int
    days: int
    points: list[ProjectOperatingTrendPoint]


class ProjectStageGoalActionResult(BaseModel):
    action_type: str
    status: str
    message: str
    resource_type: str | None = None
    resource_id: int | None = None
    resource_url: str | None = None
    detail: dict = {}


class ProjectStageGoalTimelineItem(BaseModel):
    event_type: str
    title: str
    message: str | None = None
    resource_type: str | None = None
    resource_id: int | None = None
    resource_url: str | None = None
    status: str | None = None
    detail: dict = {}
    created_at: datetime


class ProjectMvpStatusAction(BaseModel):
    action_type: str
    status: str
    message: str
    resource_type: str | None = None
    resource_id: int | None = None
    resource_url: str | None = None
    detail: dict = {}
    created_at: datetime | None = None


class ProjectMvpStatusStageGoal(BaseModel):
    goal_id: int | None = None
    goal_status: str = "missing"
    action_results: list[ProjectMvpStatusAction] = []
    placement_id: int | None = None
    share_id: int | None = None
    share_token: str | None = None
    access_log_id: int | None = None
    review_status: str = "unknown"
    metric_deltas: dict[str, float | int] = {}
    delivery_status: str = "unknown"


class ProjectMvpProviderStatus(BaseModel):
    provider_id: int
    name: str
    provider_type: str
    model_name: str
    status: str
    ready: bool
    auth_ready: bool
    supports_web_search: bool
    access_method: str
    search_mode: str
    search_access_status: str
    collection_ready: bool
    collection_blocker: str | None = None
    latest_test_ok: bool | None = None
    latest_test_error: str | None = None
    project_total_task_count: int = 0
    project_success_task_count: int = 0
    project_failed_task_count: int = 0
    project_result_count: int = 0
    project_usage_record_count: int = 0
    project_total_tokens: int = 0
    project_latest_task_id: int | None = None
    project_latest_task_status: str | None = None
    project_latest_task_error_message: str | None = None
    project_latest_result_id: int | None = None
    project_latest_result_collected_at: datetime | None = None
    missing: list[str] = []
    warnings: list[str] = []
    recommendations: list[str] = []


class ProjectMvpCrawlHealth(BaseModel):
    status: str
    ok: bool
    total_tasks: int = 0
    pending_tasks: int = 0
    running_tasks: int = 0
    success_tasks: int = 0
    failed_tasks: int = 0
    latest_task_id: int | None = None
    latest_task_status: str | None = None
    latest_task_type: str | None = None
    latest_error_message: str | None = None
    latest_result_count: int = 0
    total_result_count: int = 0
    reason: str | None = None
    next_action_label: str | None = None
    next_action_type: str | None = None
    next_action_url: str | None = None


class ProjectMvpScheduleStatus(BaseModel):
    ok: bool
    status: str
    active_schedule_count: int = 0
    hourly_schedule_count: int = 0
    due_schedule_count: int = 0
    latest_schedule_id: int | None = None
    latest_schedule_name: str | None = None
    latest_schedule_type: str | None = None
    latest_interval_hours: int | None = None
    latest_provider_count: int = 0
    latest_target_question_count: int = 0
    latest_keyword_count: int = 0
    latest_last_run_at: datetime | None = None
    latest_next_run_at: datetime | None = None
    next_action_label: str
    next_action_type: str
    next_action_url: str | None = None


class ProjectMvpContentDelivery(BaseModel):
    ok: bool
    latest_draft_id: int | None = None
    latest_review_id: int | None = None
    latest_review_score: int | None = None
    latest_review_grade: str | None = None
    approved_draft_count: int = 0
    planned_placement_count: int = 0
    published_delivery_count: int = 0
    active_share_count: int = 0
    accepted_delivery_count: int = 0
    latest_placement_id: int | None = None
    latest_share_id: int | None = None
    latest_share_token: str | None = None
    latest_access_log_id: int | None = None
    next_action_label: str
    next_action_type: str
    next_action_url: str | None = None


class ProjectMvpStatusCheck(BaseModel):
    check: str
    ok: bool
    reason: str | None = None
    next_action_label: str | None = None
    next_action_type: str | None = None
    next_action_url: str | None = None
    status: str | None = None
    total_score: int | None = None
    maturity_level: str | None = None
    event_count: int | None = None
    deliverable_count: int | None = None
    metric_deltas: dict[str, float | int] | None = None


class ProjectMvpStatus(BaseModel):
    source: str = "api"
    generated_at: datetime
    ok: bool
    user_email: str
    company_id: int
    project_id: int
    project_url: str
    crawl_task_id: int | None = None
    report_ids: list[int] = []
    latest_report_url: str | None = None
    compare_url: str | None = None
    delivery_package_url: str
    public_share_url: str | None = None
    provider_summary: dict[str, int | bool | str] = {}
    providers: list[ProjectMvpProviderStatus] = []
    crawl_health: ProjectMvpCrawlHealth | None = None
    schedule_status: ProjectMvpScheduleStatus | None = None
    content_delivery: ProjectMvpContentDelivery | None = None
    stage_goal: ProjectMvpStatusStageGoal
    checks: list[ProjectMvpStatusCheck] = []
