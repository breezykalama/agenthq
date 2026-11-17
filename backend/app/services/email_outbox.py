"""Transactional email outbox.

Identity emails (verification, password reset, organization invites) are never sent inside the
HTTP request. The request writes the token hash and an outbox row in the *same* transaction; a
background worker delivers the email only after that transaction has committed.

No raw token is ever persisted. Each outbox row stores a random nonce; the raw token is
``HMAC(key, nonce)``, where the key is derived from ``JWT_SECRET_KEY``. The token row stores
``sha256(raw token)``. At send time the worker re-derives the raw token, checks that its hash
still matches the stored hash, and clears the nonce once the row reaches a terminal state.

Delivery is at-least-once: a process crash between a successful SMTP hand-off and the status
update can cause one duplicate email after the row's lease expires.
"""

import base64
import hashlib
import hmac
import logging
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.audit_context import AUDIT_ACTOR_ROLE, AUDIT_ACTOR_USER_ID
from app.core.config import get_settings
from app.core.rate_limit import safe_identifier
from app.core.tenancy import TENANT_SESSION_KEY
from app.models.audit_log import AuditAction, AuditOutcome
from app.models.email_outbox import EmailOutbox, EmailOutboxKind, EmailOutboxStatus
from app.models.identity_token import (
    EmailVerificationToken,
    EmailVerificationTokenStatus,
    PasswordResetToken,
    PasswordResetTokenStatus,
)
from app.models.organization import Organization
from app.models.organization_invite import OrganizationInvite, OrganizationInviteStatus
from app.models.user import User
from app.repositories import audit_logs as audit_log_repository
from app.schemas.audit_log import AuditLogCreate
from app.services.email import EmailBackend, EmailDeliveryError, OutboundEmail
from app.services.email_templates import (
    organization_invite_email,
    password_reset_email,
    verification_email,
)

outbox_logger = logging.getLogger("agenthq.email.outbox")

LEASE_SECONDS = 120
RETRY_DELAYS_SECONDS = (30, 120, 600, 1800, 3600)
CLAIM_BATCH_SIZE = 20
TOKEN_DERIVATION_CONTEXT = b"agenthq:email-token-derivation:v1"

DELIVERY_AUDIT_ACTIONS: dict[EmailOutboxKind, tuple[AuditAction, AuditAction]] = {
    EmailOutboxKind.EMAIL_VERIFICATION: (
        AuditAction.AUTH_EMAIL_VERIFICATION_SENT,
        AuditAction.AUTH_EMAIL_VERIFICATION_FAILED,
    ),
    EmailOutboxKind.PASSWORD_RESET: (
        AuditAction.AUTH_PASSWORD_RESET_EMAIL_SENT,
        AuditAction.AUTH_PASSWORD_RESET_EMAIL_FAILED,
    ),
    EmailOutboxKind.ORGANIZATION_INVITE: (
        AuditAction.ORGANIZATION_INVITE_EMAIL_SENT,
        AuditAction.ORGANIZATION_INVITE_EMAIL_FAILED,
    ),
}


@dataclass(frozen=True)
class IssuedToken:
    nonce: str
    raw_token: str
    token_hash: str


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _derivation_key() -> bytes:
    secret = get_settings().jwt_secret_key.encode("utf-8")
    return hmac.new(secret, TOKEN_DERIVATION_CONTEXT, hashlib.sha256).digest()


def derive_raw_token(nonce: str) -> str:
    digest = hmac.new(_derivation_key(), bytes.fromhex(nonce), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def issue_token() -> IssuedToken:
    nonce = secrets.token_hex(32)
    raw_token = derive_raw_token(nonce)
    return IssuedToken(nonce=nonce, raw_token=raw_token, token_hash=token_digest(raw_token))


def frontend_action_url(action: str, raw_token: str) -> str:
    """Build an emailed link. The token travels in the URL fragment, which browsers never send
    to the frontend host, in Referer headers, or to third-party requests."""
    base_url = get_settings().normalized_frontend_base_url
    return f"{base_url}/?auth={action}#token={raw_token}"


def enqueue(
    db: Session,
    *,
    kind: EmailOutboxKind,
    token_id: UUID,
    issued: IssuedToken,
    user_id: UUID | None = None,
    organization_id: UUID | None = None,
) -> EmailOutbox:
    """Add an outbox row to the caller's transaction. Nothing is sent until it commits."""
    row = EmailOutbox(
        kind=kind,
        token_id=token_id,
        token_nonce=issued.nonce,
        user_id=user_id,
        organization_id=organization_id,
        status=EmailOutboxStatus.PENDING,
        attempts=0,
        next_attempt_at=datetime.now(UTC),
    )
    db.add(row)
    db.flush()
    return row


def cancel_pending_for_tokens(db: Session, kind: EmailOutboxKind, token_ids: list[UUID]) -> None:
    if not token_ids:
        return
    rows = db.scalars(
        select(EmailOutbox).where(
            EmailOutbox.kind == kind,
            EmailOutbox.token_id.in_(token_ids),
            EmailOutbox.status == EmailOutboxStatus.PENDING,
        )
    ).all()
    for row in rows:
        row.status = EmailOutboxStatus.CANCELLED
        row.token_nonce = None


# --- Delivery ---------------------------------------------------------------------------------


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _retry_delay(attempts: int) -> timedelta:
    index = min(max(attempts - 1, 0), len(RETRY_DELAYS_SECONDS) - 1)
    return timedelta(seconds=RETRY_DELAYS_SECONDS[index])


def claim_due(
    db: Session, *, now: datetime | None = None, limit: int = CLAIM_BATCH_SIZE
) -> list[UUID]:
    """Atomically lease due rows. ``SKIP LOCKED`` keeps concurrent workers from double-claiming."""
    now = now or datetime.now(UTC)
    rows = list(
        db.scalars(
            select(EmailOutbox)
            .where(
                or_(
                    and_(
                        EmailOutbox.status == EmailOutboxStatus.PENDING,
                        EmailOutbox.next_attempt_at <= now,
                    ),
                    and_(
                        EmailOutbox.status == EmailOutboxStatus.SENDING,
                        EmailOutbox.lease_expires_at <= now,
                    ),
                )
            )
            .order_by(EmailOutbox.next_attempt_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
    )
    for row in rows:
        row.status = EmailOutboxStatus.SENDING
        row.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        row.attempts += 1
    claimed = [row.id for row in rows]
    db.commit()
    return claimed


@dataclass(frozen=True)
class _PreparedMessage:
    message: OutboundEmail
    entity_type: str
    entity_id: UUID


class _TokenMismatchError(Exception):
    pass


def _check_hash(nonce: str | None, stored_hash: str) -> str:
    if nonce is None:
        raise _TokenMismatchError
    raw_token = derive_raw_token(nonce)
    if not hmac.compare_digest(token_digest(raw_token), stored_hash):
        raise _TokenMismatchError
    return raw_token


def _prepare(db: Session, row: EmailOutbox, now: datetime) -> _PreparedMessage | None:
    """Rebuild the message from current state. ``None`` means the token is no longer usable
    (superseded, used, revoked, or expired), so the email must not be sent."""
    if row.kind == EmailOutboxKind.EMAIL_VERIFICATION:
        verification = db.get(EmailVerificationToken, row.token_id)
        if (
            verification is None
            or verification.status != EmailVerificationTokenStatus.PENDING
            or _as_utc(verification.expires_at) <= now
        ):
            return None
        user = db.get(User, verification.user_id)
        if user is None or not user.is_active or user.email_verified:
            return None
        raw_token = _check_hash(row.token_nonce, verification.token_hash)
        return _PreparedMessage(
            verification_email(user.email, frontend_action_url("verify-email", raw_token)),
            "email_verification_token",
            verification.id,
        )
    if row.kind == EmailOutboxKind.PASSWORD_RESET:
        reset = db.get(PasswordResetToken, row.token_id)
        if (
            reset is None
            or reset.status != PasswordResetTokenStatus.PENDING
            or _as_utc(reset.expires_at) <= now
        ):
            return None
        user = db.get(User, reset.user_id)
        if user is None or not user.is_active:
            return None
        raw_token = _check_hash(row.token_nonce, reset.token_hash)
        return _PreparedMessage(
            password_reset_email(user.email, frontend_action_url("reset-password", raw_token)),
            "password_reset_token",
            reset.id,
        )
    invite = db.get(OrganizationInvite, row.token_id)
    if (
        invite is None
        or invite.status != OrganizationInviteStatus.PENDING
        or _as_utc(invite.expires_at) <= now
    ):
        return None
    organization = db.get(Organization, invite.organization_id)
    if organization is None:
        return None
    raw_token = _check_hash(row.token_nonce, invite.token_hash)
    lifetime = _as_utc(invite.expires_at) - _as_utc(invite.created_at)
    expires_in_days = max(1, round(lifetime.total_seconds() / 86400))
    return _PreparedMessage(
        organization_invite_email(
            invite.email,
            organization.name,
            invite.role.value,
            frontend_action_url("invite", raw_token),
            expires_in_days,
        ),
        "organization_invite",
        invite.id,
    )


def _audit_delivery(
    db: Session,
    row: EmailOutbox,
    *,
    delivered: bool,
    entity_type: str,
    entity_id: UUID,
    recipient: str | None,
    final: bool,
    error: str | None = None,
) -> None:
    sent_action, failed_action = DELIVERY_AUDIT_ACTIONS[row.kind]
    metadata: dict[str, object] = {
        "outbox_id": str(row.id),
        "email_kind": row.kind.value,
        "attempt": row.attempts,
        "final": final,
    }
    if recipient is not None:
        metadata["email_hash"] = safe_identifier(recipient)
    if error is not None:
        metadata["error"] = error
    audit_log_repository.create_audit_log_pending(
        db,
        AuditLogCreate(
            organization_id=row.organization_id,
            actor="system",
            action=sent_action if delivered else failed_action,
            entity_type=entity_type,
            entity_id=entity_id,
            outcome=AuditOutcome.SUCCESS if delivered else AuditOutcome.FAILED,
            reason=None if delivered else "Email delivery failed.",
            metadata=metadata,
        ),
    )


def _reset_session_context(db: Session, organization_id: UUID | None) -> None:
    for key in (AUDIT_ACTOR_USER_ID, AUDIT_ACTOR_ROLE, TENANT_SESSION_KEY):
        db.info.pop(key, None)
    if organization_id is not None:
        db.info[TENANT_SESSION_KEY] = organization_id


def _finish(row: EmailOutbox, status: EmailOutboxStatus, now: datetime) -> None:
    row.status = status
    row.token_nonce = None
    row.lease_expires_at = None
    if status == EmailOutboxStatus.SENT:
        row.sent_at = now
        row.last_error = None


def deliver_claimed(db: Session, backend: EmailBackend, outbox_id: UUID) -> None:
    row = db.get(EmailOutbox, outbox_id)
    if row is None or row.status != EmailOutboxStatus.SENDING:
        return
    _reset_session_context(db, row.organization_id)
    now = datetime.now(UTC)
    max_attempts = get_settings().email_outbox_max_attempts

    try:
        prepared = _prepare(db, row, now)
    except _TokenMismatchError:
        # The derivation key changed (e.g. JWT_SECRET_KEY rotation). Never send a dead link.
        _finish(row, EmailOutboxStatus.FAILED, now)
        row.last_error = "token_derivation_mismatch"
        _audit_delivery(
            db,
            row,
            delivered=False,
            entity_type="email_outbox",
            entity_id=row.id,
            recipient=None,
            final=True,
            error=row.last_error,
        )
        db.commit()
        return
    if prepared is None:
        _finish(row, EmailOutboxStatus.CANCELLED, now)
        db.commit()
        return

    error: str | None = None
    try:
        delivered = backend.send(prepared.message)
        if not delivered:
            error = "email_backend_disabled"
    except EmailDeliveryError:
        delivered = False
        error = "delivery_failed"
    except Exception as exc:
        delivered = False
        error = "unexpected_error"
        outbox_logger.warning(
            "email_outbox_unexpected_error outbox_id=%s error_type=%s",
            row.id,
            type(exc).__name__,
        )

    if delivered:
        _finish(row, EmailOutboxStatus.SENT, now)
        final = True
    elif row.attempts >= max_attempts:
        _finish(row, EmailOutboxStatus.FAILED, now)
        row.last_error = error
        final = True
    else:
        row.status = EmailOutboxStatus.PENDING
        row.lease_expires_at = None
        row.next_attempt_at = now + _retry_delay(row.attempts)
        row.last_error = error
        final = False
    _audit_delivery(
        db,
        row,
        delivered=delivered,
        entity_type=prepared.entity_type,
        entity_id=prepared.entity_id,
        recipient=prepared.message.to,
        final=final,
        error=error,
    )
    db.commit()
    if not delivered:
        outbox_logger.warning(
            "email_outbox_delivery_failed outbox_id=%s kind=%s attempt=%s final=%s error=%s",
            row.id,
            row.kind.value,
            row.attempts,
            final,
            error,
        )


def dispatch_due(db: Session, backend: EmailBackend, *, now: datetime | None = None) -> int:
    """Claim and deliver one batch. Returns the number of rows processed."""
    claimed = claim_due(db, now=now)
    for outbox_id in claimed:
        try:
            deliver_claimed(db, backend, outbox_id)
        except Exception as exc:
            db.rollback()
            outbox_logger.warning(
                "email_outbox_row_error outbox_id=%s error_type=%s",
                outbox_id,
                type(exc).__name__,
            )
    return len(claimed)


# --- Background worker ------------------------------------------------------------------------


class EmailOutboxWorker:
    """In-process polling worker. Durable because state lives in the database: rows left
    pending by a restart or sleep are picked up on the next poll."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        backend_factory: Callable[[], EmailBackend],
        poll_seconds: float,
    ) -> None:
        self._session_factory = session_factory
        self._backend_factory = backend_factory
        self._poll_seconds = poll_seconds
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="email-outbox", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def notify(self) -> None:
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                with self._session_factory() as db:
                    backend = self._backend_factory()
                    while not self._stop.is_set() and dispatch_due(db, backend) > 0:
                        pass
            except Exception as exc:
                outbox_logger.warning("email_outbox_poll_failed error_type=%s", type(exc).__name__)
            self._wake.wait(self._poll_seconds)
            self._wake.clear()


_worker: EmailOutboxWorker | None = None
_worker_lock = threading.Lock()


def start_worker(
    session_factory: Callable[[], Session],
    backend_factory: Callable[[], EmailBackend],
) -> None:
    global _worker
    with _worker_lock:
        if _worker is not None:
            return
        _worker = EmailOutboxWorker(
            session_factory, backend_factory, get_settings().email_outbox_poll_seconds
        )
        _worker.start()


def stop_worker() -> None:
    global _worker
    with _worker_lock:
        worker, _worker = _worker, None
    if worker is not None:
        worker.stop()


def notify_worker() -> None:
    """Call after the enqueuing transaction commits to deliver promptly instead of on next poll."""
    worker = _worker
    if worker is not None:
        worker.notify()
