from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.agent import AgentRiskLevel
from app.models.approval import ApprovalStatus


class ApprovalCreate(BaseModel):
    agent_id: UUID
    requested_action: str = Field(min_length=1, max_length=255)
    requested_by: str = Field(default="system", min_length=1, max_length=255)
    reason: str | None = Field(default=None, max_length=2000)
    risk_level: AgentRiskLevel


class ApprovalDecision(BaseModel):
    approver: str | None = Field(default=None, max_length=255)
    decision_reason: str | None = Field(default=None, max_length=2000)


class ApprovalRead(BaseModel):
    id: UUID
    agent_id: UUID
    requested_action: str
    requested_by: str
    reason: str | None
    status: ApprovalStatus
    risk_level: AgentRiskLevel
    approver: str | None
    decision_reason: str | None
    requested_at: datetime
    decided_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class ApprovalListResponse(BaseModel):
    items: list[ApprovalRead]
    total: int
