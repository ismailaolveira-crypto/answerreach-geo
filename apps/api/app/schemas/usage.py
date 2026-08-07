from typing import Any

from pydantic import BaseModel, ConfigDict

from app.schemas.common import TimestampedSchema


class UsageRecordRead(TimestampedSchema):
    id: int
    provider_id: int | None = None
    company_id: int | None = None
    project_id: int | None = None
    task_id: int | None = None
    crawl_result_id: int | None = None
    provider_test_run_id: int | None = None
    action: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost: float
    currency: str
    detail_json: dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class UsageSummary(BaseModel):
    company_id: int | None = None
    project_id: int | None = None
    total_records: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    total_estimated_cost: float
    currency: str
    by_action: list[dict[str, Any]]
    by_provider: list[dict[str, Any]]
