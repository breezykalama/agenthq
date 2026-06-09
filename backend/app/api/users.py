from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.pagination import PaginationParams
from app.core.security import (
    CurrentOrganizationContext,
    get_current_user,
    require_current_organization,
    require_roles,
)
from app.db.session import get_db
from app.models.user import User, UserRole
from app.schemas.user import UserListResponse, UserRead, UserUpdate
from app.services import users as user_service

router = APIRouter(
    prefix="/api/v1/users",
    tags=["users"],
    dependencies=[Depends(require_current_organization), Depends(require_roles(UserRole.ADMIN))],
)
DatabaseSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
OrganizationContext = Annotated[
    CurrentOrganizationContext,
    Depends(require_current_organization),
]


@router.get("", response_model=UserListResponse)
def list_users(
    db: DatabaseSession,
    context: OrganizationContext,
    pagination: PaginationParams,
) -> UserListResponse:
    users, total = user_service.list_users(
        db,
        current_organization_id(context),
        limit=pagination.limit,
        offset=pagination.offset,
    )
    return UserListResponse(items=users, total=total)


@router.get("/{user_id}", response_model=UserRead)
def get_user(user_id: UUID, db: DatabaseSession, context: OrganizationContext) -> UserRead:
    try:
        return user_service.get_user_by_id(db, current_organization_id(context), user_id)
    except user_service.UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        ) from exc


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: UUID,
    update: UserUpdate,
    db: DatabaseSession,
    current_user: CurrentUser,
    context: OrganizationContext,
) -> UserRead:
    try:
        return user_service.update_user(
            db,
            current_organization_id(context),
            user_id,
            update,
            current_user,
        )
    except user_service.UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        ) from exc
    except user_service.LastOrganizationAdminError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An organization must have at least one active admin.",
        ) from exc
    except user_service.GlobalUserIdentityUpdateNotAllowedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization admins cannot update global user identity fields.",
        ) from exc


@router.post("/{user_id}/deactivate", response_model=UserRead)
def deactivate_user(
    user_id: UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
    context: OrganizationContext,
) -> UserRead:
    try:
        return user_service.update_user(
            db,
            current_organization_id(context),
            user_id,
            UserUpdate(is_active=False),
            current_user,
        )
    except user_service.UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        ) from exc
    except user_service.LastOrganizationAdminError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An organization must have at least one active admin.",
        ) from exc


def current_organization_id(context: CurrentOrganizationContext) -> UUID:
    if context.current_organization is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization membership required.",
        )
    return context.current_organization.id
