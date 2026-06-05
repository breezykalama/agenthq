from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.agent import AgentRiskLevel
from app.models.execution import ExecutionStatus
from app.models.policy_rule import PolicyRuleEffect


class ExecutionCreate(BaseModel):
    agent_id: UUID
    action_name: str = Field(min_length=1, max_length=255)
    input_summary: str | None = None
    output_summary: str | None = None
    status: ExecutionStatus | None = None
    risk_level: AgentRiskLevel
    tool_id: UUID | None = None
    approval_id: UUID | None = None
    cost_usd: Decimal | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    error_message: str | None = None


class ExecutionUpdate(BaseModel):
    action_name: str | None = Field(default=None, min_length=1, max_length=255)
    input_summary: str | None = None
    output_summary: str | None = None
    status: ExecutionStatus | None = None
    risk_level: AgentRiskLevel | None = None
    tool_id: UUID | None = None
    approval_id: UUID | None = None
    cost_usd: Decimal | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    error_message: str | None = None


class ExecutionRead(BaseModel):
    id: UUID
    agent_id: UUID
    action_name: str
    input_summary: str | None
    output_summary: str | None
    status: ExecutionStatus
    risk_level: AgentRiskLevel
    tool_id: UUID | None
    approval_id: UUID | None
    policy_decision: PolicyRuleEffect | None
    policy_decision_reason: str | None
    policy_rule_id: UUID | None
    cost_usd: Decimal | None
    latency_ms: int | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ExecutionListResponse(BaseModel):
    items: list[ExecutionRead]
    total: int
