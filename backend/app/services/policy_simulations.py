from uuid import UUID

from sqlalchemy.orm import Session

from app.models.agent import AgentRiskLevel
from app.models.agent_tool import AgentTool
from app.models.governance_alert import GovernanceAlertStatus, GovernanceAlertType
from app.models.policy_rule import PolicyRule, PolicyRuleEffect, PolicyRuleScope
from app.repositories import governance_alerts as alert_repository
from app.repositories import policy_decisions as policy_decision_repository
from app.repositories import tool_governance as governance_repository
from app.schemas.policy_simulation import (
    AlertImpact,
    CoverageImpact,
    GovernanceChanges,
    GovernanceEffectImpact,
    ImpactEntity,
    ImpactEntityGroup,
    PolicyConflictWarning,
    PolicyImpactSummary,
    PolicySimulationRequest,
    PolicySimulationResponse,
)
from app.services import policy_decisions as policy_decision_service
from app.services import policy_rules as policy_rule_service
from app.services import tool_governance as governance_service


def scope_matches_request(tool: AgentTool, request: PolicySimulationRequest) -> bool:
    if request.scope == PolicyRuleScope.GLOBAL:
        return True
    if request.scope == PolicyRuleScope.AGENT:
        return tool.agent_id == request.agent_id
    return tool.agent_id == request.agent_id and tool.id == request.tool_id


def risk_matches(tool: AgentTool, request: PolicySimulationRequest) -> bool:
    severity = {
        AgentRiskLevel.LOW: 1,
        AgentRiskLevel.MEDIUM: 2,
        AgentRiskLevel.HIGH: 3,
        AgentRiskLevel.CRITICAL: 4,
    }
    return severity[tool.risk_level] >= severity[request.risk_level]


def group(items: dict[UUID, str]) -> ImpactEntityGroup:
    values = [ImpactEntity(id=item_id, name=name) for item_id, name in items.items()]
    return ImpactEntityGroup(count=len(values), items=values)


def coverage(governed: int, total: int) -> CoverageImpact:
    return CoverageImpact(
        governed_tools=governed,
        ungoverned_tools=total - governed,
        policy_coverage_percentage=0.0 if total == 0 else round(governed * 100 / total, 2),
    )


def effect_impact(tools: list[AgentTool]) -> GovernanceEffectImpact:
    items = [ImpactEntity(id=tool.id, name=tool.name) for tool in tools]
    return GovernanceEffectImpact(count=len(items), tools=items)


def matching_rules(tool: AgentTool, policies: list[PolicyRule]) -> list[PolicyRule]:
    return [
        rule
        for rule in governance_service.applicable_policies(tool, policies)
        if policy_decision_repository.risk_severity(tool.risk_level)
        >= policy_decision_repository.risk_severity(rule.risk_level)
    ]


def default_effect(risk_level: AgentRiskLevel) -> PolicyRuleEffect:
    return (
        PolicyRuleEffect.ALLOW
        if risk_level in (AgentRiskLevel.LOW, AgentRiskLevel.MEDIUM)
        else PolicyRuleEffect.REQUIRE_APPROVAL
    )


def current_effect(tool: AgentTool, policies: list[PolicyRule]) -> PolicyRuleEffect:
    rule = policy_decision_service.select_best_rule(matching_rules(tool, policies))
    return rule.effect if rule is not None else default_effect(tool.risk_level)


def proposed_wins(
    tool: AgentTool,
    request: PolicySimulationRequest,
    policies: list[PolicyRule],
) -> bool:
    if (
        not request.is_enabled
        or not scope_matches_request(tool, request)
        or not risk_matches(tool, request)
    ):
        return False
    current_best = policy_decision_service.select_best_rule(matching_rules(tool, policies))
    if current_best is None:
        return True
    proposed_rank = (
        policy_decision_service.scope_rank(request.scope),
        request.priority,
        -policy_decision_repository.risk_severity(request.risk_level),
    )
    current_rank = (
        policy_decision_service.scope_rank(current_best.scope),
        current_best.priority,
        -policy_decision_repository.risk_severity(current_best.risk_level),
    )
    return proposed_rank < current_rank


def simulate(db: Session, request: PolicySimulationRequest) -> PolicySimulationResponse:
    policy_rule_service.validate_scope(
        db,
        scope=request.scope,
        agent_id=request.agent_id,
        tool_id=request.tool_id,
    )
    tools = governance_repository.list_discovered_tools(db)
    current_policies = governance_repository.list_enabled_policy_rules(db)
    projected_base_policies = [
        rule
        for rule in current_policies
        if rule.id != request.policy_id
    ]
    current_governed = {
        tool.id
        for tool, _, _ in tools
        if tool.reviewed_at is not None
        and governance_service.applicable_policies(tool, current_policies)
    }
    scope_tools = [item for item in tools if scope_matches_request(item[0], request)]
    affected = [item for item in scope_tools if risk_matches(item[0], request)]
    projected_policies_apply = request.is_enabled
    projected_governed = set(current_governed)
    if request.policy_id is not None:
        projected_governed = {
            tool.id
            for tool, _, _ in tools
            if tool.reviewed_at is not None
            and governance_service.applicable_policies(tool, projected_base_policies)
        }
    if projected_policies_apply:
        projected_governed.update(
            tool.id for tool, _, _ in scope_tools if tool.reviewed_at is not None
        )

    warnings: list[PolicyConflictWarning] = []
    for tool, _, _ in affected if request.is_enabled else []:
        for rule in matching_rules(tool, projected_base_policies):
            conflicting = rule.effect != request.effect
            warnings.append(
                PolicyConflictWarning(
                    tool_id=tool.id,
                    tool_name=tool.name,
                    existing_policy_id=rule.id,
                    existing_policy_name=rule.name,
                    existing_effect=rule.effect,
                    proposed_effect=request.effect,
                    conflicting_effects=conflicting,
                    reason=(
                        "Conflicting effects target the same tool."
                        if conflicting
                        else "Overlapping policy scopes target the same tool."
                    ),
                )
            )

    changes: dict[PolicyRuleEffect, list[AgentTool]] = {
        effect: [] for effect in PolicyRuleEffect
    }
    for tool, _, _ in affected:
        before_effect = current_effect(tool, current_policies)
        after_effect = (
            request.effect
            if proposed_wins(tool, request, projected_base_policies)
            else current_effect(tool, projected_base_policies)
        )
        if after_effect != before_effect:
            changes[after_effect].append(tool)

    agent_names = {tool.agent_id: agent_name for tool, agent_name, _ in affected}
    server_names = {
        tool.discovered_from_mcp_server_id: server_name
        for tool, _, server_name in affected
        if tool.discovered_from_mcp_server_id is not None
    }
    tool_names = {tool.id: tool.name for tool, _, _ in affected}
    active_alerts, _ = alert_repository.list_alerts(
        db,
        status=None,
        severity=None,
        alert_type=None,
        tool_id=None,
        limit=200,
        offset=0,
    )
    resolved_tool_ids = projected_governed - current_governed
    active_alerts = [
        alert for alert in active_alerts if alert.status != GovernanceAlertStatus.RESOLVED
    ]

    return PolicySimulationResponse(
        affected_tools=group(tool_names),
        affected_agents=group(agent_names),
        affected_mcp_servers=group(server_names),
        current_coverage=coverage(len(current_governed), len(tools)),
        projected_coverage=coverage(len(projected_governed), len(tools)),
        governance_gaps_resolved=len(resolved_tool_ids),
        governance_changes=GovernanceChanges(
            becoming_blocked=effect_impact(changes[PolicyRuleEffect.BLOCK]),
            becoming_approval_required=effect_impact(
                changes[PolicyRuleEffect.REQUIRE_APPROVAL]
            ),
            becoming_explicitly_allowed=effect_impact(changes[PolicyRuleEffect.ALLOW]),
        ),
        alert_impact=AlertImpact(
            potentially_resolved_ungoverned_tool=sum(
                alert.tool_id in resolved_tool_ids
                and alert.alert_type == GovernanceAlertType.UNGOVERNED_TOOL
                for alert in active_alerts
            ),
            potentially_resolved_policy_coverage_lost=sum(
                alert.tool_id in resolved_tool_ids
                and alert.alert_type == GovernanceAlertType.POLICY_COVERAGE_LOST
                for alert in active_alerts
            ),
            potentially_created_conflicts=sum(item.conflicting_effects for item in warnings),
            potentially_created_overlaps=len(warnings),
        ),
        warning_count=len(warnings),
        warnings=warnings,
    )


def get_summary(db: Session) -> PolicyImpactSummary:
    tools = governance_repository.list_discovered_tools(db)
    policies = governance_repository.list_enabled_policy_rules(db)
    governed = sum(
        tool.reviewed_at is not None
        and bool(governance_service.applicable_policies(tool, policies))
        for tool, _, _ in tools
    )
    conflicts = 0
    for tool, _, _ in tools:
        effects = {rule.effect for rule in governance_service.applicable_policies(tool, policies)}
        if len(effects) > 1:
            conflicts += 1
    total = len(tools)
    return PolicyImpactSummary(
        policy_coverage_percentage=0.0 if total == 0 else round(governed * 100 / total, 2),
        governed_tools=governed,
        ungoverned_tools=total - governed,
        governance_gaps=total - governed,
        conflict_count=conflicts,
    )
