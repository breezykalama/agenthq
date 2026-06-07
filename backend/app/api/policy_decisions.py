from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import require_roles
from app.db.session import get_db
from app.models.user import UserRole
from app.schemas.policy_decision import PolicyDecisionRequest, PolicyDecisionResponse
from app.services import policy_decisions as policy_decision_service

router = APIRouter(
    prefix="/api/v1/policy-decisions",
    tags=["policy-decisions"],
    dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.OPERATOR))],
)
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post("/evaluate", response_model=PolicyDecisionResponse)
def evaluate_policy_decision(
    decision_request: PolicyDecisionRequest,
    db: DatabaseSession,
) -> PolicyDecisionResponse:
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
