from typing import Any

from pydantic import BaseModel, ConfigDict

from app.schemas.common import TimestampedSchema


class SystemAlertRead(TimestampedSchema):
    id: int
    company_id: int | None = None
    project_id: int | None = None
    provider_id: int | None = None
    provider_test_run_id: int | None = None
    alert_type: str
    severity: str
    status: str
    title: str
    message: str
    detail_json: dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class SystemAlertUpdate(BaseModel):
    status: str


class SystemAlertActionResult(BaseModel):
    action_type: str
    alert_id: int
    status: str
    message: str
    resource_type: str | None = None
    resource_ids: list[int] = []
    resource_url: str | None = None
    detail: dict[str, Any] = {}
