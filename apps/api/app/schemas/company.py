from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import TimestampedSchema


class CompanyBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    industry: str | None = None
    website_url: str | None = None
    description: str | None = None
    brand_aliases: list[str] = Field(default_factory=list)
    status: str = "active"


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(BaseModel):
    name: str | None = None
    industry: str | None = None
    website_url: str | None = None
    description: str | None = None
    brand_aliases: list[str] | None = None
    status: str | None = None


class CompanyRead(CompanyBase, TimestampedSchema):
    id: int

    model_config = ConfigDict(from_attributes=True)

