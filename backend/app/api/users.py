from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.pagination import PaginationParams
from app.core.security import get_current_user, require_roles
from app.db.session import get_db
from app.models.user import User, UserRole
from app.schemas.user import UserListResponse, UserRead, UserUpdate
from app.services import users as user_service

router = APIRouter(
    prefix="/api/v1/users",
    tags=["users"],
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
DatabaseSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("", response_model=UserListResponse)
def list_users(db: DatabaseSession, pagination: PaginationParams) -> UserListResponse:
    users, total = user_service.list_users(
        db,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    return UserListResponse(items=[UserRead.model_validate(user) for user in users], total=total)


@router.get("/{user_id}", response_model=UserRead)
def get_user(user_id: UUID, db: DatabaseSession) -> UserRead:
    try:
        return UserRead.model_validate(user_service.get_user_by_id(db, user_id))
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
) -> UserRead:
    try:
        return UserRead.model_validate(
            user_service.update_user(db, user_id, update, current_user)
        )
    except user_service.UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        ) from exc


@router.post("/{user_id}/deactivate", response_model=UserRead)
def deactivate_user(
    user_id: UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> UserRead:
    try:
        return UserRead.model_validate(
            user_service.update_user(db, user_id, UserUpdate(is_active=False), current_user)
        )
    except user_service.UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        ) from exc
