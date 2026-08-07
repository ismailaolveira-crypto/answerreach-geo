from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import TimestampedSchema


class BrandClaimBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    claim_text: str = Field(min_length=1)
    category: str = "product"
    source_url: str | None = None
    status: str = "active"
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    owner: str | None = None


class BrandClaimCreate(BrandClaimBase):
    pass


class BrandClaimUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    claim_text: str | None = Field(default=None, min_length=1)
    category: str | None = None
    source_url: str | None = None
    status: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    owner: str | None = None


class BrandClaimRead(BrandClaimBase, TimestampedSchema):
    id: int
    project_id: int

    model_config = ConfigDict(from_attributes=True)


class ObservationReviewUpsert(BaseModel):
    company_mentioned: bool | None = None
    company_shortlisted: bool | None = None
    company_recommended: bool | None = None
    claim_accuracy: Literal["unreviewed", "accurate", "partial", "inaccurate"] = "unreviewed"
    citation_valid: bool | None = None
    note: str | None = None


class ObservationReviewRead(ObservationReviewUpsert, TimestampedSchema):
    id: int
    crawl_result_id: int
    reviewer_user_id: int | None = None

    model_config = ConfigDict(from_attributes=True)


class ObservationRead(BaseModel):
    id: int
    task_id: int
    project_id: int
    target_question_id: int | None = None
    question_text: str | None = None
    provider_id: int | None = None
    provider_name: str = "未标注渠道"
    provider_type: str = "unknown"
    collection_method: Literal["api", "web_search_api", "web_ui_observation", "mock", "manual_import"]
    is_real_evidence: bool
    status: str
    brand_status: Literal["absent", "mentioned", "shortlisted", "recommended", "cited", "failed", "insufficient"]
    visibility_eligible: bool
    prompt_text: str
    answer_summary: str | None = None
    raw_answer: str
    collected_at: datetime | None = None
    confidence: int | None = None
    citation_count: int = 0
    owned_or_placed_citation_count: int = 0
    competitors: list[str] = Field(default_factory=list)
    review: ObservationReviewRead | None = None


class DecisionMapMetric(BaseModel):
    key: str
    label: str
    value: int | float
    help_text: str


class DecisionMapQuestion(BaseModel):
    id: int
    question_text: str
    journey_stage: str
    contains_brand: bool
    counts_for_visibility: bool
    visibility_eligible: bool


class DecisionMapCell(BaseModel):
    question_id: int
    provider_id: int | None = None
    observation_id: int | None = None
    brand_status: str
    collection_method: str | None = None
    is_real_evidence: bool = False
    collected_at: datetime | None = None


class DecisionMapRead(BaseModel):
    project_id: int
    company_name: str
    metrics: list[DecisionMapMetric]
    questions: list[DecisionMapQuestion]
    providers: list[dict]
    cells: list[DecisionMapCell]
    pending_action_count: int
    data_notice: str


class OptimizationActionBase(BaseModel):
    target_question_id: int | None = None
    source_result_ids: list[int] = Field(default_factory=list)
    title: str = Field(min_length=1, max_length=255)
    category: str = "content"
    priority: Literal["high", "medium", "low"] = "medium"
    status: Literal["proposed", "in_progress", "implemented", "verifying", "verified", "closed"] = "proposed"
    rationale: str = Field(min_length=1)
    hypothesis: str | None = None
    target_url: str | None = None
    owner: str | None = None
    change_summary: str | None = None
    implemented_at: datetime | None = None
    verification_result_id: int | None = None
    verification_summary: str | None = None
    concluded_at: datetime | None = None


class OptimizationActionCreate(OptimizationActionBase):
    pass


class OptimizationActionUpdate(BaseModel):
    target_question_id: int | None = None
    source_result_ids: list[int] | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    category: str | None = None
    priority: Literal["high", "medium", "low"] | None = None
    status: Literal["proposed", "in_progress", "implemented", "verifying", "verified", "closed"] | None = None
    rationale: str | None = Field(default=None, min_length=1)
    hypothesis: str | None = None
    target_url: str | None = None
    owner: str | None = None
    change_summary: str | None = None
    implemented_at: datetime | None = None
    verification_result_id: int | None = None
    verification_summary: str | None = None
    concluded_at: datetime | None = None


class OptimizationActionRead(OptimizationActionBase, TimestampedSchema):
    id: int
    project_id: int
    question_text: str | None = None

    model_config = ConfigDict(from_attributes=True)
