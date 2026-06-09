import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.rate_limit import enforce_auth_rate_limit, get_client_ip
from app.db.session import get_db
from app.repositories import organizations as organization_repository
from app.schemas.organization import OrganizationBootstrapRequest
from app.schemas.user import BootstrapTokenResponse
from app.services import organizations as organization_service

router = APIRouter(prefix="/api/v1/organizations", tags=["organizations"])
security_logger = logging.getLogger("agenthq.security")
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post(
    "/bootstrap",
    response_model=BootstrapTokenResponse,
    status_code=status.HTTP_201_CREATED,
)
def bootstrap_organization(
    bootstrap_request: OrganizationBootstrapRequest,
    request: Request,
    db: DatabaseSession,
    bootstrap_secret: Annotated[str | None, Header(alias="X-Bootstrap-Secret")] = None,
) -> BootstrapTokenResponse:
    if organization_repository.count_active_organizations(db) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active organization already exists.",
        )

    enforce_auth_rate_limit(request, "bootstrap")
    settings = get_settings()
    if settings.is_production and (
        settings.bootstrap_secret is None
        or bootstrap_secret is None
        or not secrets.compare_digest(bootstrap_secret, settings.bootstrap_secret)
    ):
        security_logger.warning(
            "security_bootstrap_blocked client_ip=%s",
            get_client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bootstrap authorization failed.",
        )

    try:
        return organization_service.bootstrap_organization(db, bootstrap_request)
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
