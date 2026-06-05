from uuid import UUID

from pydantic import BaseModel, Field

from app.models.agent import AgentRiskLevel
from app.models.policy_rule import PolicyRuleEffect


class PolicyDecisionRequest(BaseModel):
    agent_id: UUID
    tool_id: UUID | None = None
    requested_action: str = Field(min_length=1, max_length=255)
    risk_level: AgentRiskLevel


class PolicyDecisionResponse(BaseModel):
    decision: PolicyRuleEffect
    matched_rule_id: UUID | None
    matched_rule_name: str | None
    reason: str
    requires_approval: bool
