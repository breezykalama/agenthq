import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.rate_limit import (
    enforce_auth_rate_limit,
    get_client_ip,
    safe_identifier,
)
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import TokenResponse, UserLogin, UserRead, UserRegister
from app.services import auth as auth_service
from app.services import organizations as organization_service
from app.services import users as user_service

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
security_logger = logging.getLogger("agenthq.security")
DatabaseSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(
    registration: UserRegister,
    request: Request,
    db: DatabaseSession,
) -> UserRead:
    enforce_auth_rate_limit(request, "register")
    if not get_settings().public_registration_enabled:
        security_logger.warning(
            "security_public_registration_blocked client_ip=%s",
            get_client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Public registration is disabled. "
                "Ask your organization administrator for an invite."
            ),
        )
    try:
        return UserRead.model_validate(user_service.register_user(db, registration))
    except user_service.DuplicateUserEmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered.",
        ) from exc


@router.post("/login", response_model=TokenResponse)
def login(credentials: UserLogin, request: Request, db: DatabaseSession) -> TokenResponse:
    enforce_auth_rate_limit(request, "login", identifier=credentials.email)
    try:
        return auth_service.login(db, credentials)
    except auth_service.InvalidCredentialsError as exc:
        security_logger.warning(
            "security_login_failed client_ip=%s email_hash=%s",
            get_client_ip(request),
            safe_identifier(credentials.email),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        ) from exc


@router.get("/me", response_model=UserRead)
def me(current_user: CurrentUser, db: DatabaseSession) -> UserRead:
    return organization_service.user_read_with_membership(db, current_user)
