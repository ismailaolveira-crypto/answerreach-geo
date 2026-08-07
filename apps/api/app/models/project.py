from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    target_industry: Mapped[str | None] = mapped_column(String(255))
    target_audience: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)

    company = relationship("Company", back_populates="projects")
    target_questions = relationship(
        "TargetQuestion", back_populates="project", cascade="all, delete-orphan"
    )
    keywords = relationship("Keyword", back_populates="project", cascade="all, delete-orphan")
    competitors = relationship("Competitor", back_populates="project", cascade="all, delete-orphan")
    brand_claims = relationship("BrandClaim", cascade="all, delete-orphan")
    optimization_actions = relationship("OptimizationAction", cascade="all, delete-orphan")


class ProjectStageGoal(TimestampMixin, Base):
    __tablename__ = "project_stage_goals"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    metric_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    target_value: Mapped[float] = mapped_column(Float, nullable=False)
    baseline_value: Mapped[float] = mapped_column(Float, default=0)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    owner: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)
    note: Mapped[str | None] = mapped_column(Text)
