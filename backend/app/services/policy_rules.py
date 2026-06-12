from uuid import UUID

from sqlalchemy.orm import Session

from app.core.security import assert_resource_in_org, log_resource_access_denied
from app.models.agent import AgentRiskLevel
from app.models.audit_log import AuditAction, JsonObject
from app.models.policy_rule import PolicyRule, PolicyRuleEffect, PolicyRuleScope
from app.repositories import agent_tools as agent_tool_repository
from app.repositories import agents as agent_repository
from app.repositories import policy_rules as policy_rule_repository
from app.schemas.audit_log import AuditLogCreate
from app.schemas.policy_rule import PolicyRuleCreate, PolicyRuleRead, PolicyRuleUpdate
from app.services import audit_logs as audit_log_service
from app.services import governance_alerts as alert_service


class PolicyRuleNotFoundError(Exception):
    pass


class DuplicatePolicyRuleNameError(Exception):
    pass


class InvalidPolicyRuleScopeError(Exception):
    pass


def serialize_policy_rule(policy_rule: PolicyRule) -> JsonObject:
    return PolicyRuleRead.model_validate(policy_rule).model_dump(mode="json")


def create_policy_rule(db: Session, policy_rule_create: PolicyRuleCreate) -> PolicyRule:
    validate_unique_name(db, policy_rule_create.name)
    validate_scope(
        db,
        scope=policy_rule_create.scope,
        agent_id=policy_rule_create.agent_id,
        tool_id=policy_rule_create.tool_id,
    )

    policy_rule = policy_rule_repository.create_policy_rule(db, policy_rule_create)
    audit_log_service.create_audit_log(
        db,
        AuditLogCreate(
            action=AuditAction.POLICY_RULE_CREATED,
            entity_type="policy_rule",
            entity_id=policy_rule.id,
            before=None,
            after=serialize_policy_rule(policy_rule),
        ),
    )
    alert_service.reconcile_all_tools(db)
    return policy_rule


def list_policy_rules(
    db: Session,
    *,
    scope: PolicyRuleScope | None = None,
    agent_id: UUID | None = None,
    tool_id: UUID | None = None,
    risk_level: AgentRiskLevel | None = None,
    effect: PolicyRuleEffect | None = None,
    is_enabled: bool | None = None,
    limit: int,
    offset: int,
) -> tuple[list[PolicyRule], int]:
    return policy_rule_repository.list_policy_rules(
        db,
        scope=scope,
        agent_id=agent_id,
        tool_id=tool_id,
        risk_level=risk_level,
        effect=effect,
        is_enabled=is_enabled,
        limit=limit,
        offset=offset,
    )


def get_policy_rule_by_id(db: Session, rule_id: UUID) -> PolicyRule:
    policy_rule = policy_rule_repository.get_policy_rule_by_id(db, rule_id)
    if policy_rule is None:
        log_resource_access_denied(
            db,
            attempted_action="access_policy_rule",
            target_resource=f"policy_rule:{rule_id}",
        )
        raise PolicyRuleNotFoundError
    assert_resource_in_org(db, policy_rule, resource_name="Policy rule")
    return policy_rule


def update_policy_rule(
    db: Session,
    rule_id: UUID,
    policy_rule_update: PolicyRuleUpdate,
) -> PolicyRule:
    policy_rule = get_policy_rule_by_id(db, rule_id)
    previously_covered = alert_service.covered_tool_ids(db)
    before = serialize_policy_rule(policy_rule)
    update_values = policy_rule_update.model_dump(exclude_unset=True)
    merged_values = {
        "scope": policy_rule.scope,
        "agent_id": policy_rule.agent_id,
        "tool_id": policy_rule.tool_id,
        **update_values,
    }

    updated_name = update_values.get("name")
    if isinstance(updated_name, str) and updated_name != policy_rule.name:
        validate_unique_name(db, updated_name)

    validate_scope(
        db,
        scope=merged_values["scope"],
        agent_id=merged_values["agent_id"],
        tool_id=merged_values["tool_id"],
    )

    updated_rule = policy_rule_repository.update_policy_rule(db, policy_rule, update_values)
    audit_log_service.create_audit_log(
        db,
        AuditLogCreate(
            action=AuditAction.POLICY_RULE_UPDATED,
            entity_type="policy_rule",
            entity_id=updated_rule.id,
            before=before,
            after=serialize_policy_rule(updated_rule),
        ),
    )
    alert_service.reconcile_all_tools(db, previously_covered=previously_covered)
    return updated_rule


def soft_delete_policy_rule(db: Session, rule_id: UUID) -> None:
    policy_rule = get_policy_rule_by_id(db, rule_id)
    previously_covered = alert_service.covered_tool_ids(db)
    before = serialize_policy_rule(policy_rule)
    deleted_rule = policy_rule_repository.soft_delete_policy_rule(db, policy_rule)
    audit_log_service.create_audit_log(
        db,
        AuditLogCreate(
            action=AuditAction.POLICY_RULE_DELETED,
            entity_type="policy_rule",
            entity_id=deleted_rule.id,
            before=before,
            after=serialize_policy_rule(deleted_rule),
        ),
    )
    alert_service.reconcile_all_tools(db, previously_covered=previously_covered)


def validate_unique_name(db: Session, name: str) -> None:
    if policy_rule_repository.get_policy_rule_by_name(db, name) is not None:
        raise DuplicatePolicyRuleNameError


def validate_scope(
    db: Session,
    *,
    scope: PolicyRuleScope,
    agent_id: UUID | None,
    tool_id: UUID | None,
) -> None:
    if scope == PolicyRuleScope.GLOBAL:
        if agent_id is not None or tool_id is not None:
            raise InvalidPolicyRuleScopeError
        return

    if scope == PolicyRuleScope.AGENT:
        if agent_id is None or tool_id is not None:
            raise InvalidPolicyRuleScopeError
        if agent_repository.get_agent_by_id(db, agent_id) is None:
            raise InvalidPolicyRuleScopeError
        return

    if agent_id is None or tool_id is None:
        raise InvalidPolicyRuleScopeError
    if agent_repository.get_agent_by_id(db, agent_id) is None:
        raise InvalidPolicyRuleScopeError
    if agent_tool_repository.get_agent_tool_by_id(db, agent_id, tool_id) is None:
        raise InvalidPolicyRuleScopeError
