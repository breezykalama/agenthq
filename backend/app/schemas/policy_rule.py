from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.agent import AgentRiskLevel
from app.models.policy_rule import PolicyRuleEffect, PolicyRuleScope


class PolicyRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    scope: PolicyRuleScope
    agent_id: UUID | None = None
    tool_id: UUID | None = None
    risk_level: AgentRiskLevel
    effect: PolicyRuleEffect
    is_enabled: bool = True
    priority: int = 100


class PolicyRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    scope: PolicyRuleScope | None = None
    agent_id: UUID | None = None
    tool_id: UUID | None = None
    risk_level: AgentRiskLevel | None = None
    effect: PolicyRuleEffect | None = None
    is_enabled: bool | None = None
    priority: int | None = None


class PolicyRuleRead(BaseModel):
    id: UUID
    name: str
    description: str | None
    scope: PolicyRuleScope
    agent_id: UUID | None
    tool_id: UUID | None
    risk_level: AgentRiskLevel
    effect: PolicyRuleEffect
    is_enabled: bool
    priority: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class PolicyRuleListResponse(BaseModel):
    items: list[PolicyRuleRead]
    total: int
