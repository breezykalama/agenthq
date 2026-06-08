from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.organization import OrganizationBootstrapRequest
from app.schemas.user import BootstrapTokenResponse
from app.services import organizations as organization_service

router = APIRouter(prefix="/api/v1/organizations", tags=["organizations"])
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post(
    "/bootstrap",
    response_model=BootstrapTokenResponse,
    status_code=status.HTTP_201_CREATED,
)
def bootstrap_organization(
    request: OrganizationBootstrapRequest,
    db: DatabaseSession,
) -> BootstrapTokenResponse:
    try:
        return organization_service.bootstrap_organization(db, request)
    except organization_service.OrganizationAlreadyBootstrappedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active organization already exists.",
        ) from exc
    except organization_service.BootstrapAdminEmailExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Admin email already registered.",
        ) from exc
