from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TimestampMixin


class SystemAlert(TimestampMixin, Base):
    __tablename__ = "system_alerts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("llm_providers.id"), index=True)
    provider_test_run_id: Mapped[int | None] = mapped_column(ForeignKey("llm_provider_test_runs.id"), index=True)
    alert_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(50), default="warning", index=True)
    status: Mapped[str] = mapped_column(String(50), default="open", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    detail_json: Mapped[dict] = mapped_column(JSON, default=dict)
