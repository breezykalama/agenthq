from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.rate_limit import enforce_authenticated_rate_limit
from app.core.security import OrgPermission, require_current_organization, require_org_permission
from app.db.session import get_db
from app.schemas.policy_decision import PolicyDecisionRequest, PolicyDecisionResponse
from app.services import policy_decisions as policy_decision_service

router = APIRouter(
    prefix="/api/v1/policy-decisions",
    tags=["policy-decisions"],
    dependencies=[
        Depends(require_current_organization),
        Depends(require_org_permission(OrgPermission.MANAGE_EXECUTIONS)),
    ],
)
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post("/evaluate", response_model=PolicyDecisionResponse)
def evaluate_policy_decision(
    decision_request: PolicyDecisionRequest,
    request: Request,
    db: DatabaseSession,
) -> PolicyDecisionResponse:
    enforce_authenticated_rate_limit(
        request,
        db,
        "policy_decision",
        resource_type="policy_decision",
    )
    try:
        return policy_decision_service.evaluate_policy_decision(db, decision_request)
    except policy_decision_service.PolicyDecisionAgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found.",
        ) from exc
    except policy_decision_service.PolicyDecisionToolNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tool not found.",
        ) from exc
    except policy_decision_service.PolicyDecisionToolDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tool is disabled.",
        ) from exc
