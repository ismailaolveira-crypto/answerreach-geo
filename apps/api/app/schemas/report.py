from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.schemas.common import TimestampedSchema


class MaturityReportCreate(BaseModel):
    title: str | None = None
    report_period: str | None = None


class DiagnosticRunCreate(BaseModel):
    provider_ids: list[int] = []
    target_question_ids: list[int] = []
    keyword_ids: list[int] = []
    execute_now: bool = True
    generate_report: bool = True
    create_action_goals: bool = True
    max_estimated_cost: float | None = None
    allow_over_budget: bool = False
    title: str | None = None
    report_period: str | None = None


class DiagnosticRunResult(BaseModel):
    task_id: int
    task_status: str
    task_url: str
    report_id: int | None = None
    report_url: str | None = None
    action_goal_count: int = 0
    provider_count: int = 0
    target_question_count: int = 0
    keyword_count: int = 0
    prompt_count: int = 0
    expected_call_count: int = 0
    estimated_total_tokens: int = 0
    estimated_cost: float = 0
    currency: str = "USD"
    result_count: int = 0
    delivery_readiness_status: str | None = None
    delivery_readiness_score: int | None = None
    warnings: list[str] = []
    blockers: list[str] = []


class MaturityScoreItemRead(TimestampedSchema):
    id: int
    report_id: int
    dimension: str
    score: int
    max_score: int
    explanation: str | None = None
    evidence_json: dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class MaturityReportRead(TimestampedSchema):
    id: int
    project_id: int
    title: str
    report_period: str | None = None
    total_score: int
    maturity_level: str
    summary: str | None = None
    report_json: dict[str, Any]
    pdf_url: str | None = None
    status: str
    generated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class MaturityReportDetail(MaturityReportRead):
    score_items: list[MaturityScoreItemRead]


class MaturityReportCompare(BaseModel):
    project_id: int
    base_report: MaturityReportRead
    target_report: MaturityReportRead
    total_score_delta: int
    maturity_level_changed: bool
    metric_deltas: dict[str, Any]
    dimension_deltas: list[dict[str, Any]]
    summary: str
    recommendations: list[str]


class ReportTemplateBase(BaseModel):
    template_key: str
    name: str
    description: str | None = None
    applies_to: str = "maturity_report"
    sections_json: list[dict[str, Any]] = []
    scoring_json: dict[str, Any] = {}
    delivery_checks_json: list[dict[str, Any]] = []
    status: str = "active"
    version: int = 1


class ReportTemplateCreate(ReportTemplateBase):
    pass


class ReportTemplateUpdate(BaseModel):
    template_key: str | None = None
    name: str | None = None
    description: str | None = None
    applies_to: str | None = None
    sections_json: list[dict[str, Any]] | None = None
    scoring_json: dict[str, Any] | None = None
    delivery_checks_json: list[dict[str, Any]] | None = None
    status: str | None = None
    version: int | None = None


class ReportTemplateRead(ReportTemplateBase, TimestampedSchema):
    id: int

    model_config = ConfigDict(from_attributes=True)
