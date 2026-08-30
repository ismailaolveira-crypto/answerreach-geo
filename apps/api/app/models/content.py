from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TimestampMixin


class ContentAsset(TimestampMixin, Base):
    __tablename__ = "content_assets"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), default="article")
    source_url: Mapped[str | None] = mapped_column(String(1000))
    body_text: Mapped[str | None] = mapped_column(Text)
    publish_channel: Mapped[str | None] = mapped_column(String(255))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(50), default="draft", index=True)


class ArticleDraft(TimestampMixin, Base):
    __tablename__ = "article_drafts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    content_asset_id: Mapped[int | None] = mapped_column(ForeignKey("content_assets.id"))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    target_question_id: Mapped[int | None] = mapped_column(ForeignKey("target_questions.id"))
    target_keyword_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    source_context: Mapped[dict] = mapped_column(JSON, default=dict)
    draft_type: Mapped[str] = mapped_column(String(100), default="article")
    status: Mapped[str] = mapped_column(String(50), default="draft", index=True)
    generated_by: Mapped[str] = mapped_column(String(100), default="system")


class ArticleReview(TimestampMixin, Base):
    __tablename__ = "article_reviews"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    article_draft_id: Mapped[int] = mapped_column(ForeignKey("article_drafts.id"), nullable=False)
    total_score: Mapped[int] = mapped_column(default=0)
    grade: Mapped[str] = mapped_column(String(10), default="E")
    dimension_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    issues_json: Mapped[list[dict]] = mapped_column(JSON, default=list)
    suggestions_json: Mapped[list[dict]] = mapped_column(JSON, default=list)
    risk_expressions: Mapped[list[dict]] = mapped_column(JSON, default=list)
    review_rule_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    review_type: Mapped[str] = mapped_column(String(50), default="ai")
    status: Mapped[str] = mapped_column(String(50), default="completed", index=True)


class ContentAssetReview(TimestampMixin, Base):
    __tablename__ = "content_asset_reviews"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    content_asset_id: Mapped[int] = mapped_column(ForeignKey("content_assets.id"), nullable=False)
    total_score: Mapped[int] = mapped_column(default=0)
    grade: Mapped[str] = mapped_column(String(10), default="E")
    dimension_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    issues_json: Mapped[list[dict]] = mapped_column(JSON, default=list)
    suggestions_json: Mapped[list[dict]] = mapped_column(JSON, default=list)
    risk_expressions: Mapped[list[dict]] = mapped_column(JSON, default=list)
    review_rule_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    review_type: Mapped[str] = mapped_column(String(50), default="ai")
    status: Mapped[str] = mapped_column(String(50), default="completed", index=True)


class ReviewRule(TimestampMixin, Base):
    __tablename__ = "review_rules"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    rule_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    applies_to: Mapped[str] = mapped_column(String(50), default="article", index=True)
    max_score: Mapped[int] = mapped_column(default=10)
    weight: Mapped[int] = mapped_column(default=1)
    checks_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)
    version: Mapped[int] = mapped_column(default=1)


class PlacementRecord(TimestampMixin, Base):
    __tablename__ = "placement_records"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    content_asset_id: Mapped[int | None] = mapped_column(ForeignKey("content_assets.id"))
    article_draft_id: Mapped[int | None] = mapped_column(ForeignKey("article_drafts.id"))
    channel: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    target_url: Mapped[str | None] = mapped_column(String(1000))
    planned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(50), default="planned", index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    archive_note: Mapped[str | None] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(String(50), default="internal", index=True)
    delivery_status: Mapped[str] = mapped_column(String(50), default="not_delivered", index=True)


class DeliveryPackageShare(TimestampMixin, Base):
    __tablename__ = "delivery_package_shares"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="客户交付包")
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmation_token_encrypted: Mapped[str | None] = mapped_column(Text)


class DeliveryPackageAccessLog(TimestampMixin, Base):
    __tablename__ = "delivery_package_access_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    share_id: Mapped[int] = mapped_column(ForeignKey("delivery_package_shares.id"), nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    placement_id: Mapped[int | None] = mapped_column(ForeignKey("placement_records.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    actor_name: Mapped[str | None] = mapped_column(String(255))
    comment: Mapped[str | None] = mapped_column(Text)
    detail_json: Mapped[dict] = mapped_column(JSON, default=dict)
