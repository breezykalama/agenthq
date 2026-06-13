from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import OrgPermission, require_current_organization, require_org_permission
from app.db.session import get_db
from app.schemas.policy_simulation import (
    PolicyImpactSummary,
    PolicySimulationRequest,
    PolicySimulationResponse,
)
from app.services import policy_rules as policy_rule_service
from app.services import policy_simulations as simulation_service

router = APIRouter(
    prefix="/api/v1",
    tags=["policy-simulations"],
    dependencies=[
        Depends(require_current_organization),
        Depends(require_org_permission(OrgPermission.MANAGE_POLICIES)),
    ],
)
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post("/policy-simulations", response_model=PolicySimulationResponse)
def simulate_policy(
    request: PolicySimulationRequest,
    db: DatabaseSession,
) -> PolicySimulationResponse:
    try:
        return simulation_service.simulate(db, request)
    except policy_rule_service.InvalidPolicyRuleScopeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Policy rule scope, agent, and tool references are invalid.",
        ) from exc


@router.get("/policy-impact-summary", response_model=PolicyImpactSummary)
def get_policy_impact_summary(db: DatabaseSession) -> PolicyImpactSummary:
    return simulation_service.get_summary(db)
