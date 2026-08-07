from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class APIMessage(BaseModel):
    message: str


class TimestampedSchema(BaseModel):
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MetricsResponse(BaseModel):
    project_id: int
    company_mention_rate: float
    company_recommendation_rate: float
    competitor_mention_rate: float
    total_answers: int
    dimensions: dict[str, Any]

