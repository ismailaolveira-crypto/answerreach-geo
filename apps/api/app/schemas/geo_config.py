from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import TimestampedSchema


class TargetQuestionBase(BaseModel):
    question_text: str = Field(min_length=1)
    question_type: str = "core"
    journey_stage: str = "consideration"
    contains_brand: bool = False
    counts_for_visibility: bool = True
    variants: list[str] = Field(default_factory=list)
    priority: int = 3
    status: str = "active"


class TargetQuestionCreate(TargetQuestionBase):
    pass


class TargetQuestionUpdate(BaseModel):
    question_text: str | None = None
    question_type: str | None = None
    journey_stage: str | None = None
    contains_brand: bool | None = None
    counts_for_visibility: bool | None = None
    variants: list[str] | None = None
    priority: int | None = None
    status: str | None = None


class TargetQuestionRead(TargetQuestionBase, TimestampedSchema):
    id: int
    project_id: int

    model_config = ConfigDict(from_attributes=True)


class KeywordBase(BaseModel):
    keyword: str = Field(min_length=1, max_length=255)
    keyword_type: str = "industry"
    priority: int = 3
    status: str = "active"


class KeywordCreate(KeywordBase):
    pass


class KeywordUpdate(BaseModel):
    keyword: str | None = None
    keyword_type: str | None = None
    priority: int | None = None
    status: str | None = None


class KeywordRead(KeywordBase, TimestampedSchema):
    id: int
    project_id: int

    model_config = ConfigDict(from_attributes=True)


class CompetitorBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list)
    website_url: str | None = None
    description: str | None = None
    status: str = "active"


class CompetitorCreate(CompetitorBase):
    pass


class CompetitorUpdate(BaseModel):
    name: str | None = None
    aliases: list[str] | None = None
    website_url: str | None = None
    description: str | None = None
    status: str | None = None


class CompetitorRead(CompetitorBase, TimestampedSchema):
    id: int
    project_id: int

    model_config = ConfigDict(from_attributes=True)
