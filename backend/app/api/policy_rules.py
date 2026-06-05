from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.agent import AgentRiskLevel
from app.models.policy_rule import PolicyRuleEffect, PolicyRuleScope
from app.schemas.policy_rule import (
    PolicyRuleCreate,
    PolicyRuleListResponse,
    PolicyRuleRead,
    PolicyRuleUpdate,
)
from app.services import policy_rules as policy_rule_service

router = APIRouter(prefix="/api/v1/policy-rules", tags=["policy-rules"])
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=PolicyRuleRead, status_code=status.HTTP_201_CREATED)
def create_policy_rule(
    policy_rule_create: PolicyRuleCreate,
    db: DatabaseSession,
) -> PolicyRuleRead:
    try:
        return PolicyRuleRead.model_validate(
            policy_rule_service.create_policy_rule(db, policy_rule_create)
        )
    except policy_rule_service.DuplicatePolicyRuleNameError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A policy rule with this name already exists.",
        ) from exc
    except policy_rule_service.InvalidPolicyRuleScopeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Policy rule scope, agent, and tool references are invalid.",
        ) from exc


@router.get("", response_model=PolicyRuleListResponse)
def list_policy_rules(
    db: DatabaseSession,
    scope: Annotated[PolicyRuleScope | None, Query()] = None,
    agent_id: Annotated[UUID | None, Query()] = None,
    tool_id: Annotated[UUID | None, Query()] = None,
    risk_level: Annotated[AgentRiskLevel | None, Query()] = None,
    effect: Annotated[PolicyRuleEffect | None, Query()] = None,
    is_enabled: Annotated[bool | None, Query()] = None,
) -> PolicyRuleListResponse:
    policy_rules, total = policy_rule_service.list_policy_rules(
        db,
        scope=scope,
        agent_id=agent_id,
        tool_id=tool_id,
        risk_level=risk_level,
        effect=effect,
        is_enabled=is_enabled,
    )
    return PolicyRuleListResponse(
        items=[PolicyRuleRead.model_validate(policy_rule) for policy_rule in policy_rules],
        total=total,
    )


@router.get("/{rule_id}", response_model=PolicyRuleRead)
def get_policy_rule(rule_id: UUID, db: DatabaseSession) -> PolicyRuleRead:
    try:
        return PolicyRuleRead.model_validate(policy_rule_service.get_policy_rule_by_id(db, rule_id))
    except policy_rule_service.PolicyRuleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Policy rule not found.",
        ) from exc


@router.patch("/{rule_id}", response_model=PolicyRuleRead)
def update_policy_rule(
    rule_id: UUID,
    policy_rule_update: PolicyRuleUpdate,
    db: DatabaseSession,
) -> PolicyRuleRead:
    try:
        return PolicyRuleRead.model_validate(
            policy_rule_service.update_policy_rule(db, rule_id, policy_rule_update)
        )
    except policy_rule_service.PolicyRuleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Policy rule not found.",
        ) from exc
    except policy_rule_service.DuplicatePolicyRuleNameError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A policy rule with this name already exists.",
        ) from exc
    except policy_rule_service.InvalidPolicyRuleScopeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Policy rule scope, agent, and tool references are invalid.",
        ) from exc


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_policy_rule(rule_id: UUID, db: DatabaseSession) -> None:
    try:
        policy_rule_service.soft_delete_policy_rule(db, rule_id)
    except policy_rule_service.PolicyRuleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Policy rule not found.",
        ) from exc
