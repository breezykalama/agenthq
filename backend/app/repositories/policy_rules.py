from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models.agent import AgentRiskLevel
from app.models.policy_rule import PolicyRule, PolicyRuleEffect, PolicyRuleScope
from app.schemas.policy_rule import PolicyRuleCreate


def create_policy_rule(db: Session, policy_rule_create: PolicyRuleCreate) -> PolicyRule:
    policy_rule = PolicyRule(**policy_rule_create.model_dump())
    db.add(policy_rule)
    db.commit()
    db.refresh(policy_rule)
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
) -> tuple[list[PolicyRule], int]:
    filters: list[ColumnElement[bool]] = [PolicyRule.deleted_at.is_(None)]
    if scope is not None:
        filters.append(PolicyRule.scope == scope)
    if agent_id is not None:
        filters.append(PolicyRule.agent_id == agent_id)
    if tool_id is not None:
        filters.append(PolicyRule.tool_id == tool_id)
    if risk_level is not None:
        filters.append(PolicyRule.risk_level == risk_level)
    if effect is not None:
        filters.append(PolicyRule.effect == effect)
    if is_enabled is not None:
        filters.append(PolicyRule.is_enabled == is_enabled)

    statement = select(PolicyRule).where(*filters).order_by(PolicyRule.priority.asc())
    count_statement = select(func.count()).select_from(PolicyRule).where(*filters)

    policy_rules = list(db.scalars(statement).all())
    total = db.scalar(count_statement) or 0
    return policy_rules, total


def get_policy_rule_by_id(db: Session, rule_id: UUID) -> PolicyRule | None:
    statement = select(PolicyRule).where(
        PolicyRule.id == rule_id,
        PolicyRule.deleted_at.is_(None),
    )
    return db.scalar(statement)


def get_policy_rule_by_name(db: Session, name: str) -> PolicyRule | None:
    statement = select(PolicyRule).where(
        PolicyRule.name == name,
        PolicyRule.deleted_at.is_(None),
    )
    return db.scalar(statement)


def update_policy_rule(
    db: Session,
    policy_rule: PolicyRule,
    values: dict[str, object],
) -> PolicyRule:
    for field, value in values.items():
        setattr(policy_rule, field, value)

    db.add(policy_rule)
    db.commit()
    db.refresh(policy_rule)
    return policy_rule


def soft_delete_policy_rule(db: Session, policy_rule: PolicyRule) -> PolicyRule:
    policy_rule.deleted_at = datetime.now(UTC)
    db.add(policy_rule)
    db.commit()
    db.refresh(policy_rule)
    return policy_rule
