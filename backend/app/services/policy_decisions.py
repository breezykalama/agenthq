from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.agent import AgentRiskLevel
from app.models.audit_log import AuditAction
from app.models.policy_rule import PolicyRule, PolicyRuleEffect, PolicyRuleScope
from app.repositories import agent_tools as agent_tool_repository
from app.repositories import agents as agent_repository
from app.repositories import policy_decisions as policy_decision_repository
from app.schemas.audit_log import AuditLogCreate
from app.schemas.policy_decision import PolicyDecisionRequest, PolicyDecisionResponse
from app.services import audit_logs as audit_log_service


class PolicyDecisionAgentNotFoundError(Exception):
    pass


class PolicyDecisionToolNotFoundError(Exception):
    pass


class PolicyDecisionToolDisabledError(Exception):
    pass


def evaluate_policy_decision(
    db: Session,
    decision_request: PolicyDecisionRequest,
    *,
    commit: bool = True,
) -> PolicyDecisionResponse:
    if agent_repository.get_agent_by_id(db, decision_request.agent_id) is None:
        raise PolicyDecisionAgentNotFoundError

    if decision_request.tool_id is not None:
        tool = agent_tool_repository.get_agent_tool_by_id(
            db,
            decision_request.agent_id,
            decision_request.tool_id,
        )
        if tool is None:
            raise PolicyDecisionToolNotFoundError
        if not tool.is_enabled:
            raise PolicyDecisionToolDisabledError

    matched_rule = select_best_rule(
        policy_decision_repository.list_matching_policy_rules(
            db,
            agent_id=decision_request.agent_id,
            tool_id=decision_request.tool_id,
            risk_level=decision_request.risk_level,
        )
    )
    response = response_from_rule(matched_rule, decision_request.risk_level)
    try:
        audit_decision(db, decision_request, response)
        if commit:
            db.commit()
    except Exception:
        db.rollback()
        raise
    return response


def select_best_rule(policy_rules: list[PolicyRule]) -> PolicyRule | None:
    if not policy_rules:
        return None

    return sorted(
        policy_rules,
        key=lambda rule: (
            scope_rank(rule.scope),
            rule.priority,
            -policy_decision_repository.risk_severity(rule.risk_level),
        ),
    )[0]


def response_from_rule(
    policy_rule: PolicyRule | None,
    risk_level: AgentRiskLevel,
) -> PolicyDecisionResponse:
    if policy_rule is not None:
        return PolicyDecisionResponse(
            decision=policy_rule.effect,
            matched_rule_id=policy_rule.id,
            matched_rule_name=policy_rule.name,
            reason=f"Matched {policy_rule.scope.value}-scoped policy rule.",
            requires_approval=policy_rule.effect == PolicyRuleEffect.REQUIRE_APPROVAL,
        )

    if risk_level in {AgentRiskLevel.LOW, AgentRiskLevel.MEDIUM}:
        decision = PolicyRuleEffect.ALLOW
        reason = "No matching policy rule; low and medium risk actions are allowed by default."
    else:
        decision = PolicyRuleEffect.REQUIRE_APPROVAL
        reason = (
            "No matching policy rule; high and critical risk actions require approval by default."
        )

    return PolicyDecisionResponse(
        decision=decision,
        matched_rule_id=None,
        matched_rule_name=None,
        reason=reason,
        requires_approval=decision == PolicyRuleEffect.REQUIRE_APPROVAL,
    )


def audit_decision(
    db: Session,
    decision_request: PolicyDecisionRequest,
    decision_response: PolicyDecisionResponse,
) -> None:
    audit_log_service.create_critical_audit_log(
        db,
        AuditLogCreate(
            action=AuditAction.POLICY_DECISION_EVALUATED,
            entity_type="policy_decision",
            entity_id=uuid4(),
            before=None,
            after={
                "request": decision_request.model_dump(mode="json"),
                "response": decision_response.model_dump(mode="json"),
            },
        ),
    )


def scope_rank(scope: PolicyRuleScope) -> int:
    return {
        PolicyRuleScope.TOOL: 0,
        PolicyRuleScope.AGENT: 1,
        PolicyRuleScope.GLOBAL: 2,
    }[scope]
