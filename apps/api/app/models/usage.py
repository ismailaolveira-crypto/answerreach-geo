from sqlalchemy import JSON, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TimestampMixin


class UsageRecord(TimestampMixin, Base):
    __tablename__ = "usage_records"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("llm_providers.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("crawl_tasks.id"), index=True)
    crawl_result_id: Mapped[int | None] = mapped_column(ForeignKey("crawl_results.id"), index=True)
    provider_test_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_provider_test_runs.id"), index=True
    )
    action: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(20), default="USD")
    detail_json: Mapped[dict] = mapped_column(JSON, default=dict)
