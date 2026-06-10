from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.pagination import PaginationParams
from app.core.audit_context import set_request_audit_context
from app.core.rate_limit import enforce_auth_rate_limit
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

router = APIRouter(prefix="/api/v1/organization-invites", tags=["organization-invites"])
DatabaseSession = Annotated[Session, Depends(get_db)]
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
    db: DatabaseSession,
    context: OrganizationAdmin,
) -> OrganizationInviteCreateResponse:
    try:
        return invite_service.create_invite(db, context, invite_create)
    except invite_service.DuplicatePendingInviteError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A pending invite already exists for this email.",
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
    db: DatabaseSession,
    context: OrganizationAdmin,
) -> OrganizationInviteRead:
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
    enforce_auth_rate_limit(request, "invite_accept", db=db)
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
    except invite_service.InvalidInviteTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invite is invalid or expired.",
        ) from exc
