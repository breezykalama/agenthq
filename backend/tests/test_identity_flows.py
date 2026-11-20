from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from email_helpers import (
    capture_email,
    database_session,
    deliver_outbox,
    raw_token_from_message,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.rate_limit import reset_rate_limit_backend
from app.models.audit_log import AuditLog
from app.models.email_outbox import EmailOutbox, EmailOutboxKind, EmailOutboxStatus
from app.models.identity_token import (
    EmailVerificationToken,
    EmailVerificationTokenStatus,
    PasswordResetToken,
    PasswordResetTokenStatus,
)
from app.models.user import User
from app.repositories import identity_tokens as token_repository
from app.services import identity as identity_service
from app.services.email import EmailDeliveryError, OutboundEmail, get_email_backend
from app.services.identity import token_digest


@pytest.fixture()
def client(fresh_install_client: TestClient) -> TestClient:
    """These tests create the first organization themselves (bootstrap), so they start from a
    fresh install with no organization and no membership."""
    return fresh_install_client


JsonResponse = dict[str, Any]
ADMIN_EMAIL = "verification-admin@example.com"
ADMIN_PASSWORD = "VerificationPassword123!"
RESET_EMAIL = "password-user@example.com"
RESET_PASSWORD = "OriginalPassword123!"


def bootstrap(client: TestClient) -> JsonResponse:
    response = client.post(
        "/api/v1/organizations/bootstrap",
        json={
            "organization_name": "Verified Bank",
            "admin_full_name": "Verification Admin",
            "admin_email": ADMIN_EMAIL,
            "admin_password": ADMIN_PASSWORD,
        },
    )
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def register_reset_user(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": RESET_EMAIL, "full_name": "Password User", "password": RESET_PASSWORD},
    )
    assert response.status_code == 201
    return RESET_EMAIL


def login(client: TestClient, email: str, password: str) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return cast(str, response.json()["access_token"])


def age_tokens(client: TestClient, model: type[Any], seconds: int) -> None:
    """Move issued tokens into the past so the per-account cooldown no longer applies."""
    with database_session(client) as db:
        for token in db.scalars(select(model)).all():
            token.created_at = token.created_at - timedelta(seconds=seconds)
        db.commit()


# --- Transactional outbox ---------------------------------------------------------------------


def test_bootstrap_queues_verification_and_sends_only_after_commit(
    unauthenticated_client: TestClient,
) -> None:
    backend = capture_email(unauthenticated_client)
    bootstrap(unauthenticated_client)

    assert backend.messages == []
    with database_session(unauthenticated_client) as db:
        row = db.scalar(select(EmailOutbox))
        assert row is not None
        assert row.kind == EmailOutboxKind.EMAIL_VERIFICATION
        assert row.status == EmailOutboxStatus.PENDING
        assert row.token_nonce is not None

    assert deliver_outbox(unauthenticated_client) == 1
    assert len(backend.messages) == 1
    raw_token = raw_token_from_message(backend.messages[0].text_body)
    with database_session(unauthenticated_client) as db:
        stored = db.scalar(select(EmailVerificationToken))
        row = db.scalar(select(EmailOutbox))
        assert stored is not None and row is not None
        assert stored.token_hash == token_digest(raw_token)
        assert raw_token != stored.token_hash
        assert row.status == EmailOutboxStatus.SENT
        assert row.token_nonce is None
        assert raw_token not in str(row.__dict__)


def test_outbox_delivers_each_message_once(unauthenticated_client: TestClient) -> None:
    backend = capture_email(unauthenticated_client)
    bootstrap(unauthenticated_client)

    assert deliver_outbox(unauthenticated_client) == 1
    assert deliver_outbox(unauthenticated_client) == 0
    assert len(backend.messages) == 1


def test_delivery_failure_is_retried_audited_and_sanitized(
    unauthenticated_client: TestClient,
) -> None:
    class FailingEmailBackend:
        enabled = True

        def send(self, message: OutboundEmail) -> bool:
            raise EmailDeliveryError("private provider detail")

    bootstrap(unauthenticated_client)
    assert deliver_outbox(unauthenticated_client, FailingEmailBackend()) == 1

    with database_session(unauthenticated_client) as db:
        row = db.scalar(select(EmailOutbox))
        assert row is not None
        assert row.status == EmailOutboxStatus.PENDING
        assert row.attempts == 1
        assert row.last_error == "delivery_failed"
        assert row.token_nonce is not None
        next_attempt = row.next_attempt_at.replace(tzinfo=UTC)
        assert next_attempt > datetime.now(UTC)
        failure = db.scalar(
            select(AuditLog).where(AuditLog.action == "auth.email_verification_failed")
        )
        assert failure is not None
        assert "private provider detail" not in str(failure.event_metadata)

    # Not due yet: a second pass does nothing.
    assert deliver_outbox(unauthenticated_client, FailingEmailBackend()) == 0


def test_delivery_gives_up_after_max_attempts_and_wipes_nonce(
    unauthenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingEmailBackend:
        enabled = True

        def send(self, message: OutboundEmail) -> bool:
            raise EmailDeliveryError("down")

    monkeypatch.setenv("EMAIL_OUTBOX_MAX_ATTEMPTS", "2")
    get_settings.cache_clear()
    bootstrap(unauthenticated_client)
    for _ in range(2):
        with database_session(unauthenticated_client) as db:
            row = db.scalar(select(EmailOutbox))
            assert row is not None
            row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
        deliver_outbox(unauthenticated_client, FailingEmailBackend())

    with database_session(unauthenticated_client) as db:
        row = db.scalar(select(EmailOutbox))
        assert row is not None
        assert row.status == EmailOutboxStatus.FAILED
        assert row.token_nonce is None
        assert row.attempts == 2


def test_expired_lease_is_reclaimed(unauthenticated_client: TestClient) -> None:
    backend = capture_email(unauthenticated_client)
    bootstrap(unauthenticated_client)
    with database_session(unauthenticated_client) as db:
        row = db.scalar(select(EmailOutbox))
        assert row is not None
        row.status = EmailOutboxStatus.SENDING
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    assert deliver_outbox(unauthenticated_client) == 1
    assert len(backend.messages) == 1


def test_rotated_secret_never_sends_a_dead_link(
    unauthenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = capture_email(unauthenticated_client)
    bootstrap(unauthenticated_client)
    monkeypatch.setenv("JWT_SECRET_KEY", "a-different-secret-after-rotation-for-tests")
    get_settings.cache_clear()

    deliver_outbox(unauthenticated_client)

    assert backend.messages == []
    with database_session(unauthenticated_client) as db:
        row = db.scalar(select(EmailOutbox))
        assert row is not None
        assert row.status == EmailOutboxStatus.FAILED
        assert row.last_error == "token_derivation_mismatch"


def test_bootstrap_without_delivery_channel_does_not_require_verification(
    unauthenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMAIL_BACKEND", "disabled")
    get_settings.cache_clear()
    from app.services.email import reset_email_backend

    reset_email_backend()
    result = bootstrap(unauthenticated_client)

    assert result["user"]["email_verification_required"] is False
    with database_session(unauthenticated_client) as db:
        assert db.scalar(select(func.count()).select_from(EmailOutbox)) == 0
    invites = unauthenticated_client.get(
        "/api/v1/organization-invites", headers=bearer(result["access_token"])
    )
    assert invites.status_code == 200


# --- Email verification and enforcement -------------------------------------------------------


def test_verify_email_marks_user_and_prevents_reuse(unauthenticated_client: TestClient) -> None:
    backend = capture_email(unauthenticated_client)
    result = bootstrap(unauthenticated_client)
    deliver_outbox(unauthenticated_client)
    raw_token = raw_token_from_message(backend.messages[0].text_body)

    verified = unauthenticated_client.post("/api/v1/auth/verify-email", json={"token": raw_token})
    reused = unauthenticated_client.post("/api/v1/auth/verify-email", json={"token": raw_token})
    me = unauthenticated_client.get("/api/v1/auth/me", headers=bearer(result["access_token"]))
    audits = unauthenticated_client.get(
        "/api/v1/audit-logs", headers=bearer(result["access_token"])
    )

    assert verified.status_code == 200
    assert me.json()["email_verified"] is True
    assert me.json()["email_verified_at"] is not None
    assert reused.status_code == 400
    assert reused.json() == {"detail": "Token is invalid or expired."}
    assert audits.status_code == 200
    assert raw_token not in audits.text


def test_expired_and_invalid_verification_tokens_use_generic_error(
    unauthenticated_client: TestClient,
) -> None:
    backend = capture_email(unauthenticated_client)
    bootstrap(unauthenticated_client)
    deliver_outbox(unauthenticated_client)
    raw_token = raw_token_from_message(backend.messages[0].text_body)
    with database_session(unauthenticated_client) as db:
        stored = db.scalar(select(EmailVerificationToken))
        assert stored is not None
        stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    expired = unauthenticated_client.post("/api/v1/auth/verify-email", json={"token": raw_token})
    invalid = unauthenticated_client.post("/api/v1/auth/verify-email", json={"token": "x" * 43})

    assert expired.status_code == invalid.status_code == 400
    assert expired.json() == invalid.json() == {"detail": "Token is invalid or expired."}
    with database_session(unauthenticated_client) as db:
        stored = db.scalar(select(EmailVerificationToken))
        assert stored is not None
        assert stored.status == EmailVerificationTokenStatus.EXPIRED


def test_unverified_bootstrap_admin_is_limited_to_identity_endpoints(
    unauthenticated_client: TestClient,
) -> None:
    backend = capture_email(unauthenticated_client)
    result = bootstrap(unauthenticated_client)
    headers = bearer(result["access_token"])

    me = unauthenticated_client.get("/api/v1/auth/me", headers=headers)
    invites = unauthenticated_client.get("/api/v1/organization-invites", headers=headers)
    agents = unauthenticated_client.get("/api/v1/agents", headers=headers)
    audits = unauthenticated_client.get("/api/v1/audit-logs", headers=headers)

    assert me.status_code == 200
    assert me.json()["email_verification_required"] is True
    assert me.json()["email_verified"] is False
    for blocked in (invites, agents, audits):
        assert blocked.status_code == 403
        assert blocked.json() == {"detail": "Email verification required."}

    deliver_outbox(unauthenticated_client)
    raw_token = raw_token_from_message(backend.messages[0].text_body)
    assert (
        unauthenticated_client.post(
            "/api/v1/auth/verify-email", json={"token": raw_token}
        ).status_code
        == 200
    )
    assert (
        unauthenticated_client.get("/api/v1/organization-invites", headers=headers).status_code
        == 200
    )
    assert unauthenticated_client.get("/api/v1/agents", headers=headers).status_code == 200


def test_unverified_password_recovery_stays_available(unauthenticated_client: TestClient) -> None:
    backend = capture_email(unauthenticated_client)
    bootstrap(unauthenticated_client)
    deliver_outbox(unauthenticated_client)
    backend.messages.clear()

    forgot = unauthenticated_client.post(
        "/api/v1/auth/forgot-password", json={"email": ADMIN_EMAIL}
    )
    deliver_outbox(unauthenticated_client)

    assert forgot.status_code == 200
    assert len(backend.messages) == 1
    assert "reset-password" in backend.messages[0].text_body


def test_legacy_unverified_users_are_grandfathered(member_client: TestClient) -> None:
    # An existing (pre-v0.8.1) unverified account with an explicit membership keeps access.
    with database_session(member_client) as db:
        admin = db.scalar(select(User).where(User.email == "admin@agenthq.local"))
        assert admin is not None
        assert admin.email_verified is False
        assert admin.email_verification_required is False

    assert member_client.get("/api/v1/agents").status_code == 200


# --- Resend verification ----------------------------------------------------------------------


def test_resend_verification_supersedes_previous_link(unauthenticated_client: TestClient) -> None:
    backend = capture_email(unauthenticated_client)
    bootstrap(unauthenticated_client)
    deliver_outbox(unauthenticated_client)
    first_token = raw_token_from_message(backend.messages[0].text_body)
    age_tokens(unauthenticated_client, EmailVerificationToken, 120)

    resent = unauthenticated_client.post(
        "/api/v1/auth/resend-verification", json={"email": ADMIN_EMAIL}
    )
    deliver_outbox(unauthenticated_client)

    assert resent.status_code == 200
    assert len(backend.messages) == 2
    second_token = raw_token_from_message(backend.messages[1].text_body)
    assert second_token != first_token
    old = unauthenticated_client.post("/api/v1/auth/verify-email", json={"token": first_token})
    new = unauthenticated_client.post("/api/v1/auth/verify-email", json={"token": second_token})
    assert old.status_code == 400
    assert new.status_code == 200


def test_resend_verification_is_generic_and_skips_ineligible_accounts(
    unauthenticated_client: TestClient,
) -> None:
    backend = capture_email(unauthenticated_client)
    bootstrap(unauthenticated_client)
    deliver_outbox(unauthenticated_client)
    raw_token = raw_token_from_message(backend.messages[0].text_body)
    unauthenticated_client.post("/api/v1/auth/verify-email", json={"token": raw_token})
    backend.messages.clear()
    age_tokens(unauthenticated_client, EmailVerificationToken, 120)

    verified = unauthenticated_client.post(
        "/api/v1/auth/resend-verification", json={"email": ADMIN_EMAIL}
    )
    unknown = unauthenticated_client.post(
        "/api/v1/auth/resend-verification", json={"email": "nobody@example.com"}
    )
    deliver_outbox(unauthenticated_client)

    assert verified.status_code == unknown.status_code == 200
    assert verified.json() == unknown.json()
    assert backend.messages == []


def test_resend_verification_cooldown_is_silent(unauthenticated_client: TestClient) -> None:
    backend = capture_email(unauthenticated_client)
    bootstrap(unauthenticated_client)

    first = unauthenticated_client.post(
        "/api/v1/auth/resend-verification", json={"email": ADMIN_EMAIL}
    )
    deliver_outbox(unauthenticated_client)

    assert first.status_code == 200
    # Only the bootstrap email: the immediate resend was inside the cooldown.
    assert len(backend.messages) == 1
    with database_session(unauthenticated_client) as db:
        assert db.scalar(select(func.count()).select_from(EmailVerificationToken)) == 1


# --- Password reset ---------------------------------------------------------------------------


def test_forgot_password_is_generic_and_never_sends_inline(
    unauthenticated_client: TestClient,
) -> None:
    class ExplodingBackend:
        enabled = True

        def send(self, message: OutboundEmail) -> bool:
            raise AssertionError("SMTP must not run inside the request")

    app = cast(FastAPI, unauthenticated_client.app)
    app.dependency_overrides[get_email_backend] = lambda: ExplodingBackend()
    email = register_reset_user(unauthenticated_client)

    known = unauthenticated_client.post("/api/v1/auth/forgot-password", json={"email": email})
    unknown = unauthenticated_client.post(
        "/api/v1/auth/forgot-password", json={"email": "missing@example.com"}
    )

    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    assert known.headers["Cache-Control"] == "no-store"
    with database_session(unauthenticated_client) as db:
        assert db.scalar(select(func.count()).select_from(PasswordResetToken)) == 1
        assert db.scalar(select(func.count()).select_from(EmailOutbox)) == 1


def test_forgot_password_responses_are_padded(
    unauthenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time

    monkeypatch.setenv("IDENTITY_MIN_RESPONSE_MS", "200")
    get_settings.cache_clear()
    capture_email(unauthenticated_client)
    email = register_reset_user(unauthenticated_client)

    durations = []
    for address in (email, "missing@example.com"):
        started = time.monotonic()
        unauthenticated_client.post("/api/v1/auth/forgot-password", json={"email": address})
        durations.append(time.monotonic() - started)

    assert all(duration >= 0.2 for duration in durations)


def test_forgot_password_abuse_is_throttled_per_account(
    unauthenticated_client: TestClient,
) -> None:
    backend = capture_email(unauthenticated_client)
    email = register_reset_user(unauthenticated_client)

    for _ in range(3):
        response = unauthenticated_client.post(
            "/api/v1/auth/forgot-password", json={"email": email}
        )
        assert response.status_code == 200
    deliver_outbox(unauthenticated_client)

    assert len(backend.messages) == 1
    for _ in range(6):
        age_tokens(unauthenticated_client, PasswordResetToken, 61)
        unauthenticated_client.post("/api/v1/auth/forgot-password", json={"email": email})
    with database_session(unauthenticated_client) as db:
        recent = db.scalar(select(func.count()).select_from(PasswordResetToken))
        assert recent is not None
        assert recent <= 6


def test_superseded_reset_email_is_not_sent(unauthenticated_client: TestClient) -> None:
    backend = capture_email(unauthenticated_client)
    email = register_reset_user(unauthenticated_client)
    unauthenticated_client.post("/api/v1/auth/forgot-password", json={"email": email})
    age_tokens(unauthenticated_client, PasswordResetToken, 61)
    unauthenticated_client.post("/api/v1/auth/forgot-password", json={"email": email})

    deliver_outbox(unauthenticated_client)

    assert len(backend.messages) == 1
    raw_token = raw_token_from_message(backend.messages[0].text_body)
    with database_session(unauthenticated_client) as db:
        pending = db.scalar(
            select(PasswordResetToken).where(
                PasswordResetToken.status == PasswordResetTokenStatus.PENDING
            )
        )
        assert pending is not None
        assert pending.token_hash == token_digest(raw_token)
        statuses = {row.status for row in db.scalars(select(EmailOutbox)).all()}
        assert statuses == {EmailOutboxStatus.SENT, EmailOutboxStatus.CANCELLED}


def request_reset_token(client: TestClient, email: str) -> str:
    backend = capture_email(client)
    client.post("/api/v1/auth/forgot-password", json={"email": email})
    deliver_outbox(client)
    return raw_token_from_message(backend.messages[-1].text_body)


def test_password_reset_revokes_existing_sessions(unauthenticated_client: TestClient) -> None:
    email = register_reset_user(unauthenticated_client)
    old_session = login(unauthenticated_client, email, RESET_PASSWORD)
    assert (
        unauthenticated_client.get("/api/v1/auth/me", headers=bearer(old_session)).status_code
        == 200
    )
    raw_token = request_reset_token(unauthenticated_client, email)

    reset = unauthenticated_client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "NewAdminPassword123!"},
    )

    assert reset.status_code == 200
    rejected = unauthenticated_client.get("/api/v1/auth/me", headers=bearer(old_session))
    assert rejected.status_code == 401
    old_password = unauthenticated_client.post(
        "/api/v1/auth/login", json={"email": email, "password": RESET_PASSWORD}
    )
    assert old_password.status_code == 401
    new_session = login(unauthenticated_client, email, "NewAdminPassword123!")
    assert (
        unauthenticated_client.get("/api/v1/auth/me", headers=bearer(new_session)).status_code
        == 200
    )
    with database_session(unauthenticated_client) as db:
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None
        assert user.auth_version == 1


def test_password_reset_revokes_org_scoped_sessions(unauthenticated_client: TestClient) -> None:
    backend = capture_email(unauthenticated_client)
    result = bootstrap(unauthenticated_client)
    deliver_outbox(unauthenticated_client)
    verify_token = raw_token_from_message(backend.messages[0].text_body)
    unauthenticated_client.post("/api/v1/auth/verify-email", json={"token": verify_token})
    old_headers = bearer(result["access_token"])
    assert (
        unauthenticated_client.get("/api/v1/organization-invites", headers=old_headers).status_code
        == 200
    )

    raw_token = request_reset_token(unauthenticated_client, ADMIN_EMAIL)
    unauthenticated_client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "RotatedPassword123!"},
    )

    assert (
        unauthenticated_client.get("/api/v1/organization-invites", headers=old_headers).status_code
        == 401
    )
    new_headers = bearer(login(unauthenticated_client, ADMIN_EMAIL, "RotatedPassword123!"))
    assert (
        unauthenticated_client.get("/api/v1/organization-invites", headers=new_headers).status_code
        == 200
    )


def test_password_reset_rejects_used_token(unauthenticated_client: TestClient) -> None:
    email = register_reset_user(unauthenticated_client)
    raw_token = request_reset_token(unauthenticated_client, email)

    reset = unauthenticated_client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "NewAdminPassword123!"},
    )
    reused = unauthenticated_client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "AnotherPassword123!"},
    )

    assert reset.status_code == 200
    assert reused.status_code == 400
    login(unauthenticated_client, email, "NewAdminPassword123!")
    with database_session(unauthenticated_client) as db:
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None
        assert user.auth_version == 1
        assert "NewAdminPassword123!" not in user.password_hash


def test_concurrent_reset_consumption_is_atomic(
    unauthenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulate a racing request: the in-memory row still says pending, but the database row
    was consumed by another transaction. The conditional UPDATE must refuse it."""
    email = register_reset_user(unauthenticated_client)
    raw_token = request_reset_token(unauthenticated_client, email)
    with database_session(unauthenticated_client) as db:
        stale = db.scalar(select(PasswordResetToken))
        assert stale is not None
        db.expunge(stale)
        db.query(PasswordResetToken).update({"status": PasswordResetTokenStatus.USED})
        db.commit()

    monkeypatch.setattr(
        token_repository, "get_password_reset_by_hash", lambda db, token_hash: stale
    )
    with database_session(unauthenticated_client) as db:
        with pytest.raises(identity_service.InvalidIdentityTokenError):
            identity_service.reset_password(db, raw_token, "RacePassword123456!")
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None
        assert user.auth_version == 0


def test_concurrent_verification_consumption_is_atomic(
    unauthenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = capture_email(unauthenticated_client)
    bootstrap(unauthenticated_client)
    deliver_outbox(unauthenticated_client)
    raw_token = raw_token_from_message(backend.messages[0].text_body)
    with database_session(unauthenticated_client) as db:
        stale = db.scalar(select(EmailVerificationToken))
        assert stale is not None
        db.expunge(stale)
        db.query(EmailVerificationToken).update({"status": EmailVerificationTokenStatus.USED})
        db.commit()

    monkeypatch.setattr(
        token_repository, "get_email_verification_by_hash", lambda db, token_hash: stale
    )
    with database_session(unauthenticated_client) as db:
        with pytest.raises(identity_service.InvalidIdentityTokenError):
            identity_service.verify_email(db, raw_token)


def test_expired_password_reset_token_is_rejected(unauthenticated_client: TestClient) -> None:
    email = register_reset_user(unauthenticated_client)
    raw_token = request_reset_token(unauthenticated_client, email)
    with database_session(unauthenticated_client) as db:
        token = db.scalar(select(PasswordResetToken))
        assert token is not None
        token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    response = unauthenticated_client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "NewAdminPassword123!"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Token is invalid or expired."}


def test_tokens_never_appear_in_audit_logs(unauthenticated_client: TestClient) -> None:
    backend = capture_email(unauthenticated_client)
    email = register_reset_user(unauthenticated_client)
    unauthenticated_client.post("/api/v1/auth/forgot-password", json={"email": email})
    deliver_outbox(unauthenticated_client)
    raw_token = raw_token_from_message(backend.messages[0].text_body)
    unauthenticated_client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "NewAdminPassword123!"},
    )

    with database_session(unauthenticated_client) as db:
        rows = db.scalars(select(AuditLog)).all()
        dump = " ".join(
            f"{row.before} {row.after} {row.event_metadata} {row.reason}" for row in rows
        )
        nonces = [row.token_nonce for row in db.scalars(select(EmailOutbox)).all()]
    assert raw_token not in dump
    assert token_digest(raw_token) not in dump
    assert nonces == [None]


# --- Headers and rate limits ------------------------------------------------------------------


def test_responses_set_no_referrer_policy(unauthenticated_client: TestClient) -> None:
    response = unauthenticated_client.post("/api/v1/auth/verify-email", json={"token": "x" * 43})

    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "path", ["/api/v1/auth/forgot-password", "/api/v1/auth/resend-verification"]
)
def test_identity_email_endpoints_are_rate_limited(
    unauthenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    monkeypatch.setenv("AUTH_RATE_LIMIT_ATTEMPTS", "1")
    get_settings.cache_clear()
    reset_rate_limit_backend()

    first = unauthenticated_client.post(path, json={"email": "limited@example.com"})
    limited = unauthenticated_client.post(path, json={"email": "limited@example.com"})

    assert first.status_code == 200
    assert limited.status_code == 429
    assert "Retry-After" in limited.headers
