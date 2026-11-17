from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import CursorResult, Executable, select, update
from sqlalchemy.orm import Session

from app.core.audit_context import set_actor_audit_context
from app.core.rate_limit import safe_identifier
from app.core.security import hash_password
from app.core.tenancy import set_current_organization_id
from app.models.audit_log import AuditAction, AuditOutcome
from app.models.email_outbox import EmailOutboxKind
from app.models.identity_token import (
    EmailVerificationToken,
    EmailVerificationTokenStatus,
    PasswordResetToken,
    PasswordResetTokenStatus,
)
from app.models.user import User
from app.repositories import identity_tokens as token_repository
from app.repositories import organizations as organization_repository
from app.repositories import users as user_repository
from app.schemas.audit_log import AuditLogCreate
from app.services import audit_logs as audit_log_service
from app.services import email_outbox
from app.services.email import EmailBackend, delivery_enabled
from app.services.email_outbox import token_digest

GENERIC_TOKEN_ERROR = "Token is invalid or expired."

VERIFICATION_TOKEN_LIFETIME = timedelta(hours=24)
PASSWORD_RESET_TOKEN_LIFETIME = timedelta(minutes=30)
# Per-account abuse limits, applied silently on top of the per-IP/per-email request limiter so
# that responses stay identical whether or not a message was actually queued.
IDENTITY_EMAIL_COOLDOWN = timedelta(seconds=60)
IDENTITY_EMAIL_HOURLY_LIMIT = 5

__all__ = [
    "GENERIC_TOKEN_ERROR",
    "InvalidIdentityTokenError",
    "queue_email_verification",
    "request_email_verification",
    "request_password_reset",
    "reset_password",
    "token_digest",
    "verify_email",
]


class InvalidIdentityTokenError(Exception):
    pass


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _rowcount(db: Session, statement: Executable) -> int:
    result = cast(CursorResult[Any], db.execute(statement))
    return int(result.rowcount)


def _lock_user(db: Session, user_id: UUID) -> User | None:
    """Row-lock the user so concurrent issuance/consumption for one account is serialized."""
    return db.scalar(select(User).where(User.id == user_id).with_for_update())


def _throttled(created_times: list[datetime], now: datetime) -> bool:
    recent = [
        _as_utc(created) for created in created_times if _as_utc(created) > now - timedelta(hours=1)
    ]
    if len(recent) >= IDENTITY_EMAIL_HOURLY_LIMIT:
        return True
    return any(created > now - IDENTITY_EMAIL_COOLDOWN for created in recent)


# --- Email verification -----------------------------------------------------------------------


def queue_email_verification(db: Session, user: User) -> EmailVerificationToken:
    """Supersede pending verification tokens and queue a new link in the caller's transaction."""
    now = datetime.now(UTC)
    superseded: list[UUID] = []
    for existing in token_repository.list_email_verifications_for_user(db, user.id):
        if existing.status == EmailVerificationTokenStatus.PENDING:
            existing.status = EmailVerificationTokenStatus.REVOKED
            superseded.append(existing.id)
    email_outbox.cancel_pending_for_tokens(db, EmailOutboxKind.EMAIL_VERIFICATION, superseded)
    issued = email_outbox.issue_token()
    token = token_repository.create_email_verification_token_pending(
        db,
        EmailVerificationToken(
            user_id=user.id,
            token_hash=issued.token_hash,
            expires_at=now + VERIFICATION_TOKEN_LIFETIME,
        ),
    )
    organization_id = _single_organization_id(db, user)
    email_outbox.enqueue(
        db,
        kind=EmailOutboxKind.EMAIL_VERIFICATION,
        token_id=token.id,
        issued=issued,
        user_id=user.id,
        organization_id=organization_id,
    )
    audit_log_service.create_critical_audit_log(
        db,
        AuditLogCreate(
            organization_id=organization_id,
            actor=user.email,
            action=AuditAction.AUTH_EMAIL_VERIFICATION_REQUESTED,
            entity_type="email_verification_token",
            entity_id=token.id,
            metadata={"email_hash": safe_identifier(user.email), "delivery": "queued"},
        ),
    )
    return token


def request_email_verification(db: Session, email: str, email_backend: EmailBackend) -> bool:
    """Public resend. Returns whether a message was queued; callers must not reveal it."""
    user = user_repository.get_user_by_email(db, email.lower())
    if user is None or not user.is_active or user.email_verified:
        _record_ignored_request(db, AuditAction.AUTH_EMAIL_VERIFICATION_REQUESTED, email)
        return False
    user = _lock_user(db, user.id)
    if user is None or user.email_verified:
        db.rollback()
        return False
    set_user_audit_context(db, user)
    now = datetime.now(UTC)
    created = [
        token.created_at
        for token in token_repository.list_email_verifications_for_user(db, user.id)
    ]
    if _throttled(created, now) or not delivery_enabled(email_backend):
        _record_suppressed_request(
            db,
            AuditAction.AUTH_EMAIL_VERIFICATION_REQUESTED,
            user,
            reason=(
                "Verification email throttled."
                if delivery_enabled(email_backend)
                else "Email delivery is unavailable."
            ),
        )
        return False
    queue_email_verification(db, user)
    db.commit()
    email_outbox.notify_worker()
    return True


def verify_email(db: Session, raw_token: str) -> None:
    token = token_repository.get_email_verification_by_hash(db, token_digest(raw_token))
    now = datetime.now(UTC)
    if token is None:
        _audit_failed_token(
            db, AuditAction.AUTH_EMAIL_VERIFICATION_FAILED, "email_verification_token", None
        )
        raise InvalidIdentityTokenError
    token_id, user_id = token.id, token.user_id
    # Atomic single-use consumption: only one concurrent request can move pending -> used.
    consumed = _rowcount(
        db,
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.id == token_id,
            EmailVerificationToken.status == EmailVerificationTokenStatus.PENDING,
            EmailVerificationToken.expires_at > now,
        )
        .values(status=EmailVerificationTokenStatus.USED, used_at=now)
        .execution_options(synchronize_session=False),
    )
    if consumed != 1:
        db.execute(
            update(EmailVerificationToken)
            .where(
                EmailVerificationToken.id == token_id,
                EmailVerificationToken.status == EmailVerificationTokenStatus.PENDING,
            )
            .values(status=EmailVerificationTokenStatus.EXPIRED)
            .execution_options(synchronize_session=False)
        )
        _audit_failed_token(
            db, AuditAction.AUTH_EMAIL_VERIFICATION_FAILED, "email_verification_token", token_id
        )
        raise InvalidIdentityTokenError
    user = _lock_user(db, user_id)
    if user is None or not user.is_active:
        db.rollback()
        _audit_failed_token(
            db, AuditAction.AUTH_EMAIL_VERIFICATION_FAILED, "email_verification_token", token_id
        )
        raise InvalidIdentityTokenError
    set_user_audit_context(db, user)
    user.email_verified = True
    user.email_verified_at = now
    audit_log_service.create_critical_audit_log(
        db,
        AuditLogCreate(
            actor=user.email,
            action=AuditAction.AUTH_EMAIL_VERIFIED,
            entity_type="user",
            entity_id=user.id,
            after={"email_verified": True, "email_verified_at": now.isoformat()},
        ),
    )
    db.commit()


# --- Password reset ---------------------------------------------------------------------------


def request_password_reset(db: Session, email: str, email_backend: EmailBackend) -> bool:
    """Queue a reset link. Never sends inline. Returns whether a message was queued; callers
    must return the same response either way."""
    user = user_repository.get_user_by_email(db, email.lower())
    if user is None or not user.is_active:
        _record_ignored_request(db, AuditAction.AUTH_PASSWORD_RESET_REQUESTED, email)
        return False
    user = _lock_user(db, user.id)
    if user is None:
        db.rollback()
        return False
    set_user_audit_context(db, user)
    now = datetime.now(UTC)
    existing_tokens = token_repository.list_password_resets_for_user(db, user.id)
    if _throttled([token.created_at for token in existing_tokens], now) or not delivery_enabled(
        email_backend
    ):
        _record_suppressed_request(
            db,
            AuditAction.AUTH_PASSWORD_RESET_REQUESTED,
            user,
            reason=(
                "Password reset email throttled."
                if delivery_enabled(email_backend)
                else "Email delivery is unavailable."
            ),
        )
        return False
    superseded: list[UUID] = []
    for existing in existing_tokens:
        if existing.status == PasswordResetTokenStatus.PENDING:
            existing.status = PasswordResetTokenStatus.EXPIRED
            superseded.append(existing.id)
    email_outbox.cancel_pending_for_tokens(db, EmailOutboxKind.PASSWORD_RESET, superseded)
    issued = email_outbox.issue_token()
    token = token_repository.create_password_reset_token_pending(
        db,
        PasswordResetToken(
            user_id=user.id,
            token_hash=issued.token_hash,
            expires_at=now + PASSWORD_RESET_TOKEN_LIFETIME,
        ),
    )
    email_outbox.enqueue(
        db,
        kind=EmailOutboxKind.PASSWORD_RESET,
        token_id=token.id,
        issued=issued,
        user_id=user.id,
        organization_id=_single_organization_id(db, user),
    )
    audit_log_service.create_critical_audit_log(
        db,
        AuditLogCreate(
            actor=user.email,
            action=AuditAction.AUTH_PASSWORD_RESET_REQUESTED,
            entity_type="password_reset_token",
            entity_id=token.id,
            metadata={"email_hash": safe_identifier(user.email), "delivery": "queued"},
        ),
    )
    db.commit()
    email_outbox.notify_worker()
    return True


def reset_password(db: Session, raw_token: str, new_password: str) -> None:
    token = token_repository.get_password_reset_by_hash(db, token_digest(raw_token))
    now = datetime.now(UTC)
    if token is None:
        _audit_failed_token(
            db, AuditAction.AUTH_PASSWORD_RESET_FAILED, "password_reset_token", None
        )
        raise InvalidIdentityTokenError
    token_id, user_id = token.id, token.user_id
    consumed = _rowcount(
        db,
        update(PasswordResetToken)
        .where(
            PasswordResetToken.id == token_id,
            PasswordResetToken.status == PasswordResetTokenStatus.PENDING,
            PasswordResetToken.expires_at > now,
        )
        .values(status=PasswordResetTokenStatus.USED, used_at=now)
        .execution_options(synchronize_session=False),
    )
    if consumed != 1:
        db.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.id == token_id,
                PasswordResetToken.status == PasswordResetTokenStatus.PENDING,
            )
            .values(status=PasswordResetTokenStatus.EXPIRED)
            .execution_options(synchronize_session=False)
        )
        _audit_failed_token(
            db, AuditAction.AUTH_PASSWORD_RESET_FAILED, "password_reset_token", token_id
        )
        raise InvalidIdentityTokenError
    user = _lock_user(db, user_id)
    if user is None or not user.is_active:
        db.rollback()
        _audit_failed_token(
            db, AuditAction.AUTH_PASSWORD_RESET_FAILED, "password_reset_token", token_id
        )
        raise InvalidIdentityTokenError
    set_user_audit_context(db, user)
    # Bumping auth_version invalidates every access token issued before this point. The
    # increment is done in SQL so concurrent resets can never reuse a version.
    db.execute(
        update(User)
        .where(User.id == user_id)
        .values(
            password_hash=hash_password(new_password),
            auth_version=User.auth_version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    other_pending = list(
        db.scalars(
            select(PasswordResetToken.id).where(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.status == PasswordResetTokenStatus.PENDING,
            )
        ).all()
    )
    if other_pending:
        db.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.id.in_(other_pending))
            .values(status=PasswordResetTokenStatus.EXPIRED)
            .execution_options(synchronize_session=False)
        )
        email_outbox.cancel_pending_for_tokens(db, EmailOutboxKind.PASSWORD_RESET, other_pending)
    audit_log_service.create_critical_audit_log(
        db,
        AuditLogCreate(
            actor=user.email,
            action=AuditAction.AUTH_PASSWORD_RESET_COMPLETED,
            entity_type="user",
            entity_id=user.id,
            after={"password_changed": True, "sessions_revoked": True},
        ),
    )
    db.commit()


# --- Helpers ----------------------------------------------------------------------------------


def _single_organization_id(db: Session, user: User) -> UUID | None:
    memberships = organization_repository.list_active_memberships_for_user(db, user.id)
    if len(memberships) == 1:
        return memberships[0][1].id
    return None


def set_user_audit_context(db: Session, user: User) -> None:
    memberships = organization_repository.list_active_memberships_for_user(db, user.id)
    if len(memberships) == 1:
        membership, organization = memberships[0]
        set_current_organization_id(db, organization.id)
        set_actor_audit_context(db, user_id=user.id, role=membership.role)
    else:
        set_actor_audit_context(db, user_id=user.id, role=user.role)


def _record_ignored_request(db: Session, action: AuditAction, email: str) -> None:
    audit_log_service.record_event(
        db,
        action=action,
        resource_type="identity_request",
        resource_id=uuid4(),
        outcome=AuditOutcome.DENIED,
        reason="No eligible account.",
        metadata={"email_hash": safe_identifier(email)},
    )


def _record_suppressed_request(
    db: Session, action: AuditAction, user: User, *, reason: str
) -> None:
    audit_log_service.record_event(
        db,
        action=action,
        resource_type="user",
        resource_id=user.id,
        outcome=AuditOutcome.DENIED,
        reason=reason,
        metadata={"email_hash": safe_identifier(user.email)},
        actor=user.email,
    )


def _audit_failed_token(
    db: Session,
    action: AuditAction,
    resource_type: str,
    resource_id: UUID | None,
) -> None:
    audit_log_service.record_event(
        db,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=AuditOutcome.FAILED,
        reason=GENERIC_TOKEN_ERROR,
    )
