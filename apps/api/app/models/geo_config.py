from sqlalchemy import JSON, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin


class TargetQuestion(TimestampMixin, Base):
    __tablename__ = "target_questions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(String(100), default="core")
    journey_stage: Mapped[str] = mapped_column(String(50), default="consideration", index=True)
    contains_brand: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    counts_for_visibility: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    variants: Mapped[list[str]] = mapped_column(JSON, default=list)
    priority: Mapped[int] = mapped_column(default=3)
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)

    project = relationship("Project", back_populates="target_questions")


class Keyword(TimestampMixin, Base):
    __tablename__ = "keywords"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    keyword: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    keyword_type: Mapped[str] = mapped_column(String(100), default="industry")
    priority: Mapped[int] = mapped_column(default=3)
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)

    project = relationship("Project", back_populates="keywords")


class Competitor(TimestampMixin, Base):
    __tablename__ = "competitors"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    website_url: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)

    project = relationship("Project", back_populates="competitors")
