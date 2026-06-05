from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import AgentRiskLevel
from app.models.policy_rule import PolicyRule, PolicyRuleScope


def list_matching_policy_rules(
    db: Session,
    *,
    agent_id: UUID,
    tool_id: UUID | None,
    risk_level: AgentRiskLevel,
) -> list[PolicyRule]:
    candidate_scopes = [PolicyRuleScope.GLOBAL, PolicyRuleScope.AGENT]
    if tool_id is not None:
        candidate_scopes.append(PolicyRuleScope.TOOL)

    statement = select(PolicyRule).where(
        PolicyRule.deleted_at.is_(None),
        PolicyRule.is_enabled.is_(True),
        PolicyRule.scope.in_(candidate_scopes),
    )
    policy_rules = list(db.scalars(statement).all())
    requested_severity = risk_severity(risk_level)

    return [
        rule
        for rule in policy_rules
        if scope_matches(rule, agent_id=agent_id, tool_id=tool_id)
        and requested_severity >= risk_severity(rule.risk_level)
    ]


def scope_matches(rule: PolicyRule, *, agent_id: UUID, tool_id: UUID | None) -> bool:
    if rule.scope == PolicyRuleScope.GLOBAL:
        return True
    if rule.scope == PolicyRuleScope.AGENT:
        return rule.agent_id == agent_id
    return rule.agent_id == agent_id and rule.tool_id == tool_id


def risk_severity(risk_level: AgentRiskLevel) -> int:
    return {
        AgentRiskLevel.LOW: 1,
        AgentRiskLevel.MEDIUM: 2,
        AgentRiskLevel.HIGH: 3,
        AgentRiskLevel.CRITICAL: 4,
    }[risk_level]
