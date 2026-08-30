from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import TimestampedSchema


class ArticleDraftGenerate(BaseModel):
    title: str | None = None
    target_question_id: int | None = None
    draft_type: str = "faq_article"
    topic: str | None = None
    source_context: dict[str, Any] | None = None


class ArticleDraftRead(TimestampedSchema):
    id: int
    project_id: int
    content_asset_id: int | None = None
    title: str
    summary: str | None = None
    body_text: str
    target_question_id: int | None = None
    target_keyword_ids: list[int]
    source_context: dict[str, Any] = {}
    draft_type: str
    status: str
    generated_by: str

    model_config = ConfigDict(from_attributes=True)


class ArticleDraftUpdate(BaseModel):
    title: str | None = None
    summary: str | None = None
    body_text: str | None = None
    status: str | None = None


class ArticleReviewCreate(BaseModel):
    review_type: str = "ai"


class HumanReviewDecision(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    comment: str | None = None


class ArticleReviewRead(TimestampedSchema):
    id: int
    article_draft_id: int
    total_score: int
    grade: str
    dimension_scores: dict[str, int]
    issues_json: list[dict[str, Any]]
    suggestions_json: list[dict[str, Any]]
    risk_expressions: list[dict[str, Any]]
    review_rule_snapshot: dict[str, Any] = {}
    reviewer_id: int | None = None
    review_type: str
    status: str

    model_config = ConfigDict(from_attributes=True)


class ContentAssetReviewCreate(BaseModel):
    review_type: str = "ai"


class ContentAssetReviewRead(TimestampedSchema):
    id: int
    content_asset_id: int
    total_score: int
    grade: str
    dimension_scores: dict[str, int]
    issues_json: list[dict[str, Any]]
    suggestions_json: list[dict[str, Any]]
    risk_expressions: list[dict[str, Any]]
    review_rule_snapshot: dict[str, Any] = {}
    review_type: str
    status: str

    model_config = ConfigDict(from_attributes=True)


class ReviewRuleCreate(BaseModel):
    rule_key: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    applies_to: str = "article"
    max_score: int = Field(default=10, ge=1, le=100)
    weight: int = Field(default=1, ge=1, le=10)
    checks_json: dict[str, Any] = {}
    status: str = "active"
    version: int = Field(default=1, ge=1)


class ReviewRuleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    applies_to: str | None = None
    max_score: int | None = Field(default=None, ge=1, le=100)
    weight: int | None = Field(default=None, ge=1, le=10)
    checks_json: dict[str, Any] | None = None
    status: str | None = None
    version: int | None = Field(default=None, ge=1)


class ReviewRuleRead(TimestampedSchema):
    id: int
    rule_key: str
    name: str
    description: str | None = None
    applies_to: str
    max_score: int
    weight: int
    checks_json: dict[str, Any]
    status: str
    version: int

    model_config = ConfigDict(from_attributes=True)


class ContentAssetCreate(BaseModel):
    company_id: int
    project_id: int | None = None
    title: str = Field(min_length=1)
    content_type: str = "article"
    source_url: str | None = None
    body_text: str | None = None
    publish_channel: str | None = None
    published_at: datetime | None = None
    status: str = "draft"


class ContentAssetBulkCreate(BaseModel):
    items: list[ContentAssetCreate]


class ContentAssetUpdate(BaseModel):
    title: str | None = None
    content_type: str | None = None
    source_url: str | None = None
    body_text: str | None = None
    publish_channel: str | None = None
    published_at: datetime | None = None
    status: str | None = None


class ContentAssetRead(TimestampedSchema):
    id: int
    company_id: int
    project_id: int | None = None
    title: str
    content_type: str
    source_url: str | None = None
    body_text: str | None = None
    publish_channel: str | None = None
    published_at: datetime | None = None
    status: str

    model_config = ConfigDict(from_attributes=True)


class PlacementRecordBase(BaseModel):
    content_asset_id: int | None = None
    article_draft_id: int | None = None
    channel: str = Field(min_length=1)
    target_url: str | None = None
    planned_at: datetime | None = None
    published_at: datetime | None = None
    status: str = "planned"
    notes: str | None = None
    archive_note: str | None = None
    visibility: str = Field(default="internal", pattern="^(internal|customer_visible)$")
    delivery_status: str = Field(default="not_delivered", pattern="^(not_delivered|ready|delivered|accepted)$")


class PlacementRecordCreate(PlacementRecordBase):
    pass


class PlacementRecordUpdate(BaseModel):
    content_asset_id: int | None = None
    article_draft_id: int | None = None
    channel: str | None = None
    target_url: str | None = None
    planned_at: datetime | None = None
    published_at: datetime | None = None
    status: str | None = None
    notes: str | None = None
    archive_note: str | None = None
    visibility: str | None = Field(default=None, pattern="^(internal|customer_visible)$")
    delivery_status: str | None = Field(default=None, pattern="^(not_delivered|ready|delivered|accepted)$")


class PlacementRecordRead(PlacementRecordBase, TimestampedSchema):
    id: int
    project_id: int

    model_config = ConfigDict(from_attributes=True)


class PlacementImpactRead(BaseModel):
    placement: PlacementRecordRead
    baseline_time: datetime
    before: dict[str, float | int]
    after: dict[str, float | int]
    source_after_appearances: int
    summary: str
    recommendations: list[str]
    review_report: dict[str, Any]


class DeliveryPackageShareCreate(BaseModel):
    name: str = Field(default="客户交付包", min_length=1, max_length=255)
    expires_at: datetime | None = None


class DeliveryPackageShareRead(TimestampedSchema):
    id: int
    project_id: int
    token: str
    name: str
    status: str
    expires_at: datetime | None = None
    created_by_user_id: int | None = None
    last_accessed_at: datetime | None = None
    confirmation_token: str | None = None

    model_config = ConfigDict(from_attributes=True)


class DeliveryPackageAccessLogRead(TimestampedSchema):
    id: int
    share_id: int
    project_id: int
    placement_id: int | None = None
    event_type: str
    actor_name: str | None = None
    comment: str | None = None
    detail_json: dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class PublicDeliveryConfirmRequest(BaseModel):
    confirmation_token: str = Field(min_length=20, max_length=200)
    actor_name: str = Field(min_length=1, max_length=255)
    comment: str | None = Field(default=None, max_length=1000)


class PublicDeliveryPackageRead(BaseModel):
    project: dict[str, Any]
    share: dict[str, Any]
    deliverables: list[dict[str, Any]]
