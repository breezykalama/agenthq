import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.audit_context import set_actor_audit_context, set_request_audit_context
from app.core.config import get_settings
from app.core.rate_limit import (
    enforce_auth_rate_limit,
    get_client_ip,
    safe_identifier,
)
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.audit_log import AuditAction, AuditOutcome
from app.models.user import User
from app.repositories import organizations as organization_repository
from app.repositories import users as user_repository
from app.schemas.user import TokenResponse, UserLogin, UserRead, UserRegister
from app.services import audit_logs as audit_log_service
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
    set_request_audit_context(db, request)
    enforce_auth_rate_limit(request, "register", db=db)
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
    set_request_audit_context(db, request)
    enforce_auth_rate_limit(request, "login", identifier=credentials.email, db=db)
    try:
        return auth_service.login(db, credentials)
    except auth_service.InvalidCredentialsError as exc:
        user = user_repository.get_user_by_email(db, credentials.email.lower())
        if user is not None:
            memberships = organization_repository.list_active_memberships_for_user(db, user.id)
            if len(memberships) == 1:
                membership, organization = memberships[0]
                set_actor_audit_context(db, user_id=user.id, role=membership.role)
                db.info["organization_id"] = organization.id
        audit_log_service.record_event(
            db,
            action=AuditAction.AUTH_LOGIN_FAILED,
            resource_type="user",
            resource_id=user.id if user else None,
            outcome=AuditOutcome.FAILED,
            reason="Invalid login credentials.",
            metadata={"email_hash": safe_identifier(credentials.email)},
        )
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
