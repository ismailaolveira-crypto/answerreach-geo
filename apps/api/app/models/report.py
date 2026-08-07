from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TimestampMixin


class MaturityReport(TimestampMixin, Base):
    __tablename__ = "maturity_reports"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    report_period: Mapped[str | None] = mapped_column(String(100))
    total_score: Mapped[int] = mapped_column(default=0)
    maturity_level: Mapped[str] = mapped_column(String(50), default="L1")
    summary: Mapped[str | None] = mapped_column(Text)
    report_json: Mapped[dict] = mapped_column(JSON, default=dict)
    pdf_url: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(50), default="generated", index=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MaturityScoreItem(TimestampMixin, Base):
    __tablename__ = "maturity_score_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("maturity_reports.id"), nullable=False)
    dimension: Mapped[str] = mapped_column(String(100), nullable=False)
    score: Mapped[int] = mapped_column(default=0)
    max_score: Mapped[int] = mapped_column(default=100)
    explanation: Mapped[str | None] = mapped_column(Text)
    evidence_json: Mapped[dict] = mapped_column(JSON, default=dict)


class ReportTemplate(TimestampMixin, Base):
    __tablename__ = "report_templates"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    template_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    applies_to: Mapped[str] = mapped_column(String(50), default="maturity_report", index=True)
    sections_json: Mapped[list[dict]] = mapped_column(JSON, default=list)
    scoring_json: Mapped[dict] = mapped_column(JSON, default=dict)
    delivery_checks_json: Mapped[list[dict]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)
    version: Mapped[int] = mapped_column(default=1)
