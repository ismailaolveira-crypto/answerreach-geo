from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.user import UserRead


WorkspaceRole = Literal["owner", "admin", "operator", "reviewer", "viewer"]


class WorkspaceMembershipRead(BaseModel):
    id: int
    workspace_id: int
    user_id: int
    role: WorkspaceRole
    status: str
    joined_at: datetime
    user: UserRead


class WorkspaceMembershipUpdate(BaseModel):
    role: WorkspaceRole


class WorkspaceInvitationCreate(BaseModel):
    email: EmailStr
    role: WorkspaceRole = "viewer"
    expires_in_hours: int = Field(default=72, ge=1, le=168)


class WorkspaceInvitationRead(BaseModel):
    id: int
    workspace_id: int
    email: EmailStr
    role: WorkspaceRole
    status: str
    invited_by_user_id: int
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class WorkspaceInvitationCreated(WorkspaceInvitationRead):
    invite_token: str
    invite_path: str


class WorkspaceInvitationPreview(BaseModel):
    workspace_id: int
    workspace_name: str
    email_hint: str
    role: WorkspaceRole
    expires_at: datetime
    status: str


class WorkspaceInvitationAccept(BaseModel):
    token: str = Field(min_length=32, max_length=300)
    name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=255)


class WorkspaceInvitationAcceptResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead
    workspace_id: int


class LocalAgentEnrollmentCreated(BaseModel):
    workspace_id: int
    enrollment_token: str
    expires_at: datetime
    command_hint: str


FORBIDDEN_STATUS_KEYS = {
    "authorization",
    "cookie",
    "cookies",
    "local_storage",
    "password",
    "secret",
    "token",
}

FORBIDDEN_STATUS_KEY_PARTS = (
    "authorization",
    "cookie",
    "local_storage",
    "localstorage",
    "password",
    "secret",
    "storage_state",
    "token",
)


def _reject_secret_shaped_keys(value: Any) -> Any:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized_key = str(key).strip().lower().replace("-", "_")
            if normalized_key in FORBIDDEN_STATUS_KEYS or any(
                part in normalized_key for part in FORBIDDEN_STATUS_KEY_PARTS
            ):
                raise ValueError(f"secret-shaped status field is not allowed: {key}")
            _reject_secret_shaped_keys(nested)
    elif isinstance(value, list):
        for item in value:
            _reject_secret_shaped_keys(item)
    return value


class LocalAgentEnrollRequest(BaseModel):
    enrollment_token: str = Field(min_length=32, max_length=300)
    name: str = Field(min_length=1, max_length=120)
    hostname: str = Field(min_length=1, max_length=255)
    platform: str = Field(min_length=1, max_length=80)
    agent_version: str = Field(min_length=1, max_length=40)
    capabilities: dict = Field(default_factory=dict)
    health: dict = Field(default_factory=dict)

    @field_validator("capabilities", "health")
    @classmethod
    def status_is_non_secret(cls, value: dict) -> dict:
        return _reject_secret_shaped_keys(value)


class LocalAgentHeartbeat(BaseModel):
    agent_version: str = Field(min_length=1, max_length=40)
    capabilities: dict = Field(default_factory=dict)
    health: dict = Field(default_factory=dict)

    @field_validator("capabilities", "health")
    @classmethod
    def status_is_non_secret(cls, value: dict) -> dict:
        return _reject_secret_shaped_keys(value)


class LocalAgentNodeRead(BaseModel):
    id: int
    workspace_id: int
    owner_user_id: int
    name: str
    hostname: str
    platform: str
    agent_version: str
    status: str
    execution_mode: Literal["status_only"]
    capabilities: dict
    health: dict
    last_seen_at: datetime
    online: bool
    disabled_at: datetime | None


class LocalAgentEnrolled(LocalAgentNodeRead):
    device_token: str
