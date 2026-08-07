from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TimestampMixin


class LLMProvider(TimestampMixin, Base):
    __tablename__ = "llm_providers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    provider_type: Mapped[str] = mapped_column(String(100), nullable=False)
    api_base_url: Mapped[str | None] = mapped_column(String(500))
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    auth_config: Mapped[dict] = mapped_column(JSON, default=dict)
    cost_rule: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)


class LLMProviderTestRun(TimestampMixin, Base):
    __tablename__ = "llm_provider_test_runs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("llm_providers.id"), nullable=False, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    ok: Mapped[bool] = mapped_column(default=False, index=True)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(255))
    industry: Mapped[str | None] = mapped_column(String(255))
    answer_summary: Mapped[str | None] = mapped_column(Text)
    raw_answer_preview: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)


class CrawlTask(TimestampMixin, Base):
    __tablename__ = "crawl_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(100), default="manual_batch")
    schedule_type: Mapped[str] = mapped_column(String(100), default="manual")
    provider_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    target_question_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    keyword_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    sample_runs_per_prompt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)


class CrawlSchedule(TimestampMixin, Base):
    __tablename__ = "crawl_schedules"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    schedule_type: Mapped[str] = mapped_column(String(100), default="hourly")
    interval_hours: Mapped[int] = mapped_column(Integer, default=1)
    provider_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    target_question_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    keyword_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    sample_runs_per_prompt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class CrawlTaskLog(TimestampMixin, Base):
    __tablename__ = "crawl_task_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("crawl_tasks.id"), nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(50), default="info", index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    detail_json: Mapped[dict] = mapped_column(JSON, default=dict)


class CrawlResult(TimestampMixin, Base):
    __tablename__ = "crawl_results"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("crawl_tasks.id"), nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    target_question_id: Mapped[int | None] = mapped_column(ForeignKey("target_questions.id"))
    keyword_id: Mapped[int | None] = mapped_column(ForeignKey("keywords.id"))
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("llm_providers.id"))
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    raw_answer: Mapped[str] = mapped_column(Text, nullable=False)
    answer_summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="success", index=True)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnswerAnalysis(TimestampMixin, Base):
    __tablename__ = "answer_analysis"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    crawl_result_id: Mapped[int] = mapped_column(ForeignKey("crawl_results.id"), nullable=False)
    company_mentioned: Mapped[bool] = mapped_column(default=False)
    company_recommended: Mapped[bool] = mapped_column(default=False)
    company_rank: Mapped[int | None] = mapped_column()
    sentiment: Mapped[str] = mapped_column(String(50), default="neutral")
    confidence: Mapped[int] = mapped_column(default=50)
    analysis_json: Mapped[dict] = mapped_column(JSON, default=dict)


class MentionedEntity(TimestampMixin, Base):
    __tablename__ = "mentioned_entities"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    crawl_result_id: Mapped[int] = mapped_column(ForeignKey("crawl_results.id"), nullable=False)
    entity_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(100), default="unknown")
    is_company: Mapped[bool] = mapped_column(default=False)
    is_competitor: Mapped[bool] = mapped_column(default=False)
    mention_count: Mapped[int] = mapped_column(default=1)
    recommendation_rank: Mapped[int | None] = mapped_column()
    context_excerpt: Mapped[str | None] = mapped_column(Text)


class CitationSource(TimestampMixin, Base):
    __tablename__ = "citation_sources"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    crawl_result_id: Mapped[int] = mapped_column(ForeignKey("crawl_results.id"), nullable=False)
    source_title: Mapped[str | None] = mapped_column(String(500))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    source_domain: Mapped[str | None] = mapped_column(String(255), index=True)
    source_type: Mapped[str] = mapped_column(String(100), default="unknown")
    is_owned: Mapped[bool] = mapped_column(default=False)
    is_placed: Mapped[bool] = mapped_column(default=False)
    crawlable_score: Mapped[int] = mapped_column(default=50)
    ai_readiness_score: Mapped[int] = mapped_column(default=50)
