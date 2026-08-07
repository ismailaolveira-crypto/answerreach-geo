from typing import Any

from pydantic import ConfigDict

from app.schemas.common import TimestampedSchema


class AuditLogRead(TimestampedSchema):
    id: int
    actor_user_id: int | None = None
    actor_role: str | None = None
    action: str
    resource_type: str
    resource_id: int | None = None
    project_id: int | None = None
    company_id: int | None = None
    detail_json: dict[str, Any]

    model_config = ConfigDict(from_attributes=True)
