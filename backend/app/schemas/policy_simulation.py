from uuid import UUID

from pydantic import BaseModel, Field

from app.models.agent import AgentRiskLevel
from app.models.policy_rule import PolicyRuleEffect, PolicyRuleScope


class PolicySimulationRequest(BaseModel):
    policy_id: UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    scope: PolicyRuleScope
    agent_id: UUID | None = None
    tool_id: UUID | None = None
    risk_level: AgentRiskLevel
    effect: PolicyRuleEffect
    is_enabled: bool = True
    priority: int = 100


class ImpactEntity(BaseModel):
    id: UUID
    name: str


class ImpactEntityGroup(BaseModel):
    count: int
    items: list[ImpactEntity]


class CoverageImpact(BaseModel):
    governed_tools: int
    ungoverned_tools: int
    policy_coverage_percentage: float


class GovernanceEffectImpact(BaseModel):
    count: int
    tools: list[ImpactEntity]


class GovernanceChanges(BaseModel):
    becoming_blocked: GovernanceEffectImpact
    becoming_approval_required: GovernanceEffectImpact
    becoming_explicitly_allowed: GovernanceEffectImpact


class AlertImpact(BaseModel):
    potentially_resolved_ungoverned_tool: int
    potentially_resolved_policy_coverage_lost: int
    potentially_created_conflicts: int
    potentially_created_overlaps: int


class PolicyConflictWarning(BaseModel):
    tool_id: UUID
    tool_name: str
    existing_policy_id: UUID
    existing_policy_name: str
    existing_effect: PolicyRuleEffect
    proposed_effect: PolicyRuleEffect
    conflicting_effects: bool
    reason: str


class PolicySimulationResponse(BaseModel):
    affected_tools: ImpactEntityGroup
    affected_agents: ImpactEntityGroup
    affected_mcp_servers: ImpactEntityGroup
    current_coverage: CoverageImpact
    projected_coverage: CoverageImpact
    governance_gaps_resolved: int
    governance_changes: GovernanceChanges
    alert_impact: AlertImpact
    warning_count: int
    warnings: list[PolicyConflictWarning]


class PolicyImpactSummary(BaseModel):
    policy_coverage_percentage: float
    governed_tools: int
    ungoverned_tools: int
    governance_gaps: int
    conflict_count: int
