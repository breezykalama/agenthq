from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.pagination import PaginationParams
from app.core.audit_context import set_request_audit_context
from app.core.rate_limit import enforce_auth_rate_limit, enforce_authenticated_rate_limit
from app.core.security import CurrentOrganizationContext, require_current_organization_admin
from app.db.session import get_db
from app.models.organization_invite import OrganizationInviteStatus
from app.schemas.organization_invite import (
    OrganizationInviteAccept,
    OrganizationInviteCreate,
    OrganizationInviteCreateResponse,
    OrganizationInviteListResponse,
    OrganizationInviteRead,
)
from app.schemas.user import BootstrapTokenResponse
from app.services import organization_invites as invite_service
from app.services.email import EmailBackend, EmailDeliveryError, get_email_backend

router = APIRouter(prefix="/api/v1/organization-invites", tags=["organization-invites"])
DatabaseSession = Annotated[Session, Depends(get_db)]
EmailService = Annotated[EmailBackend, Depends(get_email_backend)]
OrganizationAdmin = Annotated[
    CurrentOrganizationContext,
    Depends(require_current_organization_admin),
]


@router.post(
    "",
    response_model=OrganizationInviteCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_invite(
    invite_create: OrganizationInviteCreate,
    request: Request,
    db: DatabaseSession,
    context: OrganizationAdmin,
    email_backend: EmailService,
) -> OrganizationInviteCreateResponse:
    enforce_authenticated_rate_limit(
        request,
        db,
        "invite_create",
        resource_type="organization_invite",
    )
    try:
        return invite_service.create_invite(db, context, invite_create, email_backend)
    except invite_service.DuplicatePendingInviteError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A pending invite already exists for this email.",
        ) from exc
    except EmailDeliveryError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invitation email could not be delivered. Please try again.",
        ) from exc


@router.get("", response_model=OrganizationInviteListResponse)
def list_invites(
    db: DatabaseSession,
    context: OrganizationAdmin,
    pagination: PaginationParams,
    status_filter: Annotated[OrganizationInviteStatus | None, Query(alias="status")] = None,
    email: Annotated[str | None, Query()] = None,
) -> OrganizationInviteListResponse:
    invites, total = invite_service.list_invites(
        db,
        context,
        status=status_filter,
        email=email,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    return OrganizationInviteListResponse(
        items=[OrganizationInviteRead.model_validate(invite) for invite in invites],
        total=total,
    )


@router.post("/{invite_id}/revoke", response_model=OrganizationInviteRead)
def revoke_invite(
    invite_id: UUID,
    request: Request,
    db: DatabaseSession,
    context: OrganizationAdmin,
) -> OrganizationInviteRead:
    enforce_authenticated_rate_limit(
        request,
        db,
        "invite_revoke",
        resource_type="organization_invite",
        resource_id=invite_id,
    )
    try:
        return OrganizationInviteRead.model_validate(
            invite_service.revoke_invite(db, context, invite_id)
        )
    except invite_service.OrganizationInviteNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization invite not found.",
        ) from exc
    except invite_service.InvalidInviteTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending, unexpired invites can be revoked.",
        ) from exc


@router.post("/accept", response_model=BootstrapTokenResponse)
def accept_invite(
    accept: OrganizationInviteAccept,
    request: Request,
    db: DatabaseSession,
) -> BootstrapTokenResponse:
    set_request_audit_context(db, request)
    enforce_auth_rate_limit(request, "invite_accept", identifier=accept.token, db=db)
    try:
        return invite_service.accept_invite(db, accept)
    except invite_service.InviteFullNameRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Full name is required to accept this invite.",
        ) from exc
    except invite_service.DuplicateOrganizationMembershipError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a member of this organization.",
        ) from exc
    except invite_service.MultipleOrganizationsNotSupportedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Multiple organizations are not yet supported.",
        ) from exc
    except invite_service.InvalidInviteTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invite is invalid or expired.",
        ) from exc
