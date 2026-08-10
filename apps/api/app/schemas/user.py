from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.common import TimestampedSchema


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=6)
    company_id: int | None = None
    phone: str | None = None
    role: str = "company_admin"
    status: str = "active"


class UserUpdate(BaseModel):
    company_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = None
    role: str | None = None
    status: str | None = None
    password: str | None = Field(default=None, min_length=6)


class UserRead(TimestampedSchema):
    id: int
    company_id: int | None = None
    name: str
    email: EmailStr
    phone: str | None = None
    role: str
    status: str
    last_login_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class TenantRegistrationRequest(BaseModel):
    """Public signup payload for a new, isolated GEO tenant."""

    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=12, max_length=255)
    company_name: str = Field(min_length=1, max_length=255)
    brand_name: str = Field(min_length=1, max_length=255)
    website_url: str | None = Field(default=None, max_length=500)


class TenantRegistrationResponse(LoginResponse):
    workspace_id: int
