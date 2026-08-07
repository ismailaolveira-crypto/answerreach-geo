from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TimestampMixin


class BrandClaim(TimestampMixin, Base):
    __tablename__ = "brand_claims"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(80), default="product")
    source_url: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner: Mapped[str | None] = mapped_column(String(255))


class ObservationReview(TimestampMixin, Base):
    __tablename__ = "observation_reviews"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    crawl_result_id: Mapped[int] = mapped_column(ForeignKey("crawl_results.id"), nullable=False, unique=True, index=True)
    reviewer_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    company_mentioned: Mapped[bool | None] = mapped_column(Boolean)
    company_shortlisted: Mapped[bool | None] = mapped_column(Boolean)
    company_recommended: Mapped[bool | None] = mapped_column(Boolean)
    claim_accuracy: Mapped[str] = mapped_column(String(50), default="unreviewed")
    citation_valid: Mapped[bool | None] = mapped_column(Boolean)
    note: Mapped[str | None] = mapped_column(Text)


class OptimizationAction(TimestampMixin, Base):
    __tablename__ = "optimization_actions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    target_question_id: Mapped[int | None] = mapped_column(ForeignKey("target_questions.id"), index=True)
    source_result_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(80), default="content")
    priority: Mapped[str] = mapped_column(String(30), default="medium", index=True)
    status: Mapped[str] = mapped_column(String(50), default="proposed", index=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    hypothesis: Mapped[str | None] = mapped_column(Text)
    target_url: Mapped[str | None] = mapped_column(String(1000))
    owner: Mapped[str | None] = mapped_column(String(255))
    change_summary: Mapped[str | None] = mapped_column(Text)
    implemented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_result_id: Mapped[int | None] = mapped_column(ForeignKey("crawl_results.id"), index=True)
    verification_summary: Mapped[str | None] = mapped_column(Text)
    concluded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
