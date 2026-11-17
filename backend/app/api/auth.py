import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
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
from app.schemas.identity import (
    EmailVerificationRequest,
    ForgotPasswordRequest,
    IdentityActionResponse,
    PasswordResetRequest,
    ResendVerificationRequest,
)
from app.schemas.user import TokenResponse, UserLogin, UserRead, UserRegister
from app.services import audit_logs as audit_log_service
from app.services import auth as auth_service
from app.services import identity as identity_service
from app.services import organizations as organization_service
from app.services import users as user_service
from app.services.email import EmailBackend, get_email_backend

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
security_logger = logging.getLogger("agenthq.security")
DatabaseSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
EmailService = Annotated[EmailBackend, Depends(get_email_backend)]

GENERIC_PASSWORD_RESET_MESSAGE = (
    "If an active account exists for that email, a password reset link has been sent."
)
GENERIC_RESEND_VERIFICATION_MESSAGE = (
    "If that account still needs verification, a new verification link has been sent."
)


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


@router.post("/verify-email", response_model=IdentityActionResponse)
def verify_email(
    verification: EmailVerificationRequest,
    request: Request,
    db: DatabaseSession,
) -> IdentityActionResponse:
    set_request_audit_context(db, request)
    enforce_auth_rate_limit(request, "verify_email", identifier=verification.token, db=db)
    try:
        identity_service.verify_email(db, verification.token)
    except identity_service.InvalidIdentityTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=identity_service.GENERIC_TOKEN_ERROR,
        ) from exc
    return IdentityActionResponse(message="Email verified successfully.")


def _pad_identity_response(started: float) -> None:
    """Hold the response to a fixed floor so account existence is not visible in latency.
    Email delivery is already off the request path (outbox); this hides residual DB work."""
    remaining = get_settings().identity_min_response_ms / 1000 - (time.monotonic() - started)
    if remaining > 0:
        time.sleep(remaining)


@router.post("/forgot-password", response_model=IdentityActionResponse)
def forgot_password(
    forgot: ForgotPasswordRequest,
    request: Request,
    response: Response,
    db: DatabaseSession,
    email_backend: EmailService,
) -> IdentityActionResponse:
    started = time.monotonic()
    response.headers["Cache-Control"] = "no-store"
    set_request_audit_context(db, request)
    enforce_auth_rate_limit(request, "forgot_password", identifier=forgot.email, db=db)
    identity_service.request_password_reset(db, forgot.email, email_backend)
    _pad_identity_response(started)
    return IdentityActionResponse(message=GENERIC_PASSWORD_RESET_MESSAGE)


@router.post("/resend-verification", response_model=IdentityActionResponse)
def resend_verification(
    resend: ResendVerificationRequest,
    request: Request,
    response: Response,
    db: DatabaseSession,
    email_backend: EmailService,
) -> IdentityActionResponse:
    started = time.monotonic()
    response.headers["Cache-Control"] = "no-store"
    set_request_audit_context(db, request)
    enforce_auth_rate_limit(request, "resend_verification", identifier=resend.email, db=db)
    identity_service.request_email_verification(db, resend.email, email_backend)
    _pad_identity_response(started)
    return IdentityActionResponse(message=GENERIC_RESEND_VERIFICATION_MESSAGE)


@router.post("/reset-password", response_model=IdentityActionResponse)
def reset_password(
    reset: PasswordResetRequest,
    request: Request,
    db: DatabaseSession,
) -> IdentityActionResponse:
    set_request_audit_context(db, request)
    enforce_auth_rate_limit(request, "reset_password", identifier=reset.token, db=db)
    try:
        identity_service.reset_password(db, reset.token, reset.new_password)
    except identity_service.InvalidIdentityTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=identity_service.GENERIC_TOKEN_ERROR,
        ) from exc
    return IdentityActionResponse(message="Password reset successfully.")
