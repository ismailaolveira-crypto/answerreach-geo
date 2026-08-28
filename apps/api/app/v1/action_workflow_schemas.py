from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ActionType = Literal[
    "article",
    "official_site",
    "structured_data",
    "third_party_source",
    "legacy_unclassified",
]
TargetType = Literal["platform", "official_page", "schema", "external_source"]


class ActionTargetCreate(BaseModel):
    target_key: str = Field(min_length=1, max_length=160)
    target_type: TargetType
    platform_key: str | None = Field(default=None, max_length=80)
    display_name: str = Field(min_length=1, max_length=255)
    target_ref: str = Field(min_length=1, max_length=1500)


class ActionTargetRead(BaseModel):
    id: int
    workspace_id: int
    action_id: int
    target_key: str
    target_type: str
    platform_key: str | None = None
    display_name: str
    target_ref: str
    delivery_status: str
    recorded_delivery_status: str | None = None
    status_source: str = "action_target"
    status_note: str | None = None
    distribution_target_id: int | None = None
    ordinal: int
    metadata_json: dict = Field(default_factory=dict)
    completed_at: datetime | None = None
    completed_by_user_id: int | None = None
    verified_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ActionEvidenceRead(BaseModel):
    id: int
    workspace_id: int
    action_id: int
    target_id: int
    evidence_type: str
    source_url: str | None = None
    artifact_uri: str | None = None
    sha256: str
    verification_status: str
    detail: dict = Field(default_factory=dict)
    submitted_by_user_id: int
    verified_by_user_id: int | None = None
    submitted_at: datetime
    verified_at: datetime | None = None
    supersedes_evidence_id: int | None = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ActionApprovalRead(BaseModel):
    id: int
    workspace_id: int
    action_id: int
    target_id: int | None = None
    approval_type: str
    status: str
    version: int
    requested_by_user_id: int
    reviewer_user_id: int
    due_at: datetime
    requested_at: datetime
    decided_at: datetime | None = None
    note: str | None = None
    subject_fingerprint: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ActionDetailRead(BaseModel):
    id: int
    workspace_id: int
    question_plan_id: int | None = None
    source_evidence_id: int | None = None
    opportunity_id: int | None = None
    title: str
    rationale: str
    hypothesis: str | None = None
    priority: str
    status: str
    stage: str
    baseline_snapshot: dict = Field(default_factory=dict)
    selected_scope: dict = Field(default_factory=dict)
    measurement_plan: dict = Field(default_factory=dict)
    blocked_reason: str | None = None
    selected_at: datetime | None = None
    completed_at: datetime | None = None
    action_type: str
    deliverable_type: str
    workflow_version: str
    assignee_user_id: int | None = None
    due_at: datetime | None = None
    approval_due_at: datetime | None = None
    approval_requested_at: datetime | None = None
    blocked_reason_code: str | None = None
    blocked_note: str | None = None
    affected_question_ids: list[int] = Field(default_factory=list)
    affected_model_keys: list[str] = Field(default_factory=list)
    scope_fingerprint: str | None = None
    measurement_status: str
    completed_target_count: int = 0
    retest_eligible_target_count: int = 0
    eligible_target_ids: list[int] = Field(default_factory=list)
    is_overdue: bool = False
    next_action: str
    targets: list[ActionTargetRead] = Field(default_factory=list)
    approvals: list[ActionApprovalRead] = Field(default_factory=list)
    evidence: list[ActionEvidenceRead] = Field(default_factory=list)


class ActionClassifyRequest(BaseModel):
    action_type: Literal["article", "official_site", "structured_data", "third_party_source"]
    deliverable_type: str = Field(min_length=1, max_length=60)
    targets: list[ActionTargetCreate] = Field(min_length=1, max_length=50)


class ActionAcceptRequest(BaseModel):
    assignee_user_id: int = Field(ge=1)
    due_at: datetime


class ActionAssignRequest(BaseModel):
    assignee_user_id: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=1000)


class ActionRescheduleRequest(BaseModel):
    due_at: datetime
    reason: str = Field(min_length=1, max_length=1000)


class ActionBlockRequest(BaseModel):
    reason_code: Literal[
        "waiting_owner",
        "waiting_approval",
        "waiting_external",
        "missing_evidence",
        "technical_issue",
        "other",
    ]
    note: str = Field(min_length=1, max_length=2000)


class ActionUnblockRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class TargetTransitionRequest(BaseModel):
    to_status: str = Field(min_length=1, max_length=50)
    note: str | None = Field(default=None, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=80)


class ActionEvidenceCreate(BaseModel):
    evidence_type: Literal[
        "public_url",
        "same_domain_readback",
        "source_code",
        "schema_validation",
        "external_publication",
    ]
    source_url: str | None = Field(default=None, max_length=1500)
    artifact_uri: str | None = Field(default=None, max_length=1500)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    detail: dict = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=80)
    supersedes_evidence_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_source_or_artifact(self) -> "ActionEvidenceCreate":
        if not self.source_url and not self.artifact_uri:
            raise ValueError("source_url 或 artifact_uri 至少填写一个")
        if self.artifact_uri and not self.source_url and not self.sha256:
            raise ValueError("仅提交工件时必须提供 sha256")
        return self


class ActionApprovalCreate(BaseModel):
    target_id: int | None = Field(default=None, ge=1)
    approval_type: Literal[
        "fact",
        "platform_draft",
        "brand_legal",
        "technical",
        "external_content",
    ]
    reviewer_user_id: int = Field(ge=1)
    due_at: datetime
    subject_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    note: str | None = Field(default=None, max_length=2000)


class ActionApprovalDecision(BaseModel):
    decision: Literal["approved", "changes_requested"]
    note: str | None = Field(default=None, max_length=2000)


class ActionRetestCreate(BaseModel):
    target_ids: list[int] = Field(min_length=1, max_length=50)
    idempotency_key: str = Field(min_length=8, max_length=80)
