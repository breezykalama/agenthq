import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.audit_context import set_request_audit_context
from app.core.config import get_settings
from app.core.rate_limit import enforce_auth_rate_limit, get_client_ip
from app.core.security import (
    EMAIL_VERIFICATION_REQUIRED_DETAIL,
    get_current_user,
    requires_email_verification,
)
from app.db.session import get_db
from app.models.user import User
from app.schemas.organization import (
    OrganizationBootstrapRequest,
    OrganizationMembershipListResponse,
)
from app.schemas.user import BootstrapTokenResponse
from app.services import organizations as organization_service
from app.services.email import EmailBackend, EmailDeliveryError, get_email_backend

router = APIRouter(prefix="/api/v1/organizations", tags=["organizations"])
security_logger = logging.getLogger("agenthq.security")
DatabaseSession = Annotated[Session, Depends(get_db)]
EmailService = Annotated[EmailBackend, Depends(get_email_backend)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("", response_model=OrganizationMembershipListResponse)
def list_my_organizations(
    current_user: CurrentUser,
    db: DatabaseSession,
) -> OrganizationMembershipListResponse:
    """The caller's own active memberships in non-deleted organizations, for choosing one.

    Needs no organization selection (that is what it is for) and ignores the organization
    header. Applies the same email-verification gate as every organization-scoped route.
    """
    if requires_email_verification(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=EMAIL_VERIFICATION_REQUIRED_DETAIL,
        )
    items = organization_service.list_user_memberships(db, current_user)
    return OrganizationMembershipListResponse(items=items, total=len(items))


@router.post(
    "/bootstrap",
    response_model=BootstrapTokenResponse,
    status_code=status.HTTP_201_CREATED,
)
def bootstrap_organization(
    bootstrap_request: OrganizationBootstrapRequest,
    request: Request,
    db: DatabaseSession,
    email_backend: EmailService,
    bootstrap_secret: Annotated[str | None, Header(alias="X-Bootstrap-Secret")] = None,
) -> BootstrapTokenResponse:
    set_request_audit_context(db, request)
    if organization_service.bootstrap_blocked(db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active organization already exists.",
        )

    enforce_auth_rate_limit(request, "bootstrap", db=db)
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
        return organization_service.bootstrap_organization(db, bootstrap_request, email_backend)
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
    except EmailDeliveryError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Organization email could not be delivered. Please try again.",
        ) from exc
