"""Resend HTTPS email backend. Every HTTP exchange goes through httpx.MockTransport: no network,
no real email."""

import json
import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from email_helpers import capture_email, database_session, deliver_outbox, raw_token_from_message
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.models.audit_log import AuditLog
from app.models.email_outbox import EmailOutbox, EmailOutboxKind, EmailOutboxStatus
from app.services import email_outbox
from app.services.email import (
    RESEND_API_URL,
    EmailDeliveryError,
    OutboundEmail,
    ResendEmailBackend,
    classify_resend_error,
    get_email_backend,
    reset_email_backend,
)


@pytest.fixture()
def client(fresh_install_client: TestClient) -> TestClient:
    """These tests create the first organization themselves (bootstrap), so they start from a
    fresh install with no organization and no membership."""
    return fresh_install_client


API_KEY = "re_TestOnlyKey_a1b2c3d4e5f6g7h8"
SENDER = "AgentHQ Staging <no-reply@staging.example.com>"
ADMIN_EMAIL = "resend-admin@example.com"
ADMIN_PASSWORD = "ResendAdminPassword123!"
SECRET_BODY_MARKER = "SECRET-LINK-a9f8e7"

Handler = Callable[[httpx.Request], httpx.Response]


class FakeResend:
    """Records requests; mimics Resend's idempotency (same key -> original id, no new send)."""

    def __init__(self, responder: Callable[[httpx.Request, int], httpx.Response] | None = None):
        self.requests: list[httpx.Request] = []
        self.delivered: dict[str, str] = {}  # idempotency key -> provider id
        self.unkeyed_deliveries = 0
        self._responder = responder
        self._lock = threading.Lock()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            self.requests.append(request)
            attempt = len(self.requests)
            if self._responder is not None:
                return self._responder(request, attempt)
            return self.accept(request)

    def accept(self, request: httpx.Request) -> httpx.Response:
        key = request.headers.get("Idempotency-Key")
        if key is None:
            self.unkeyed_deliveries += 1
            return httpx.Response(200, json={"id": f"unkeyed-{self.unkeyed_deliveries}"})
        provider_id = self.delivered.setdefault(key, f"email-{len(self.delivered) + 1}")
        return httpx.Response(200, json={"id": provider_id})

    @property
    def unique_deliveries(self) -> int:
        return len(self.delivered) + self.unkeyed_deliveries

    def payload(self, index: int = -1) -> dict[str, Any]:
        body: dict[str, Any] = json.loads(self.requests[index].content)
        return body


def resend_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "DATABASE_URL": "postgresql://agenthq:agenthq@localhost:5432/agenthq",
        "EMAIL_BACKEND": "resend",
        "RESEND_API_KEY": API_KEY,
        "EMAIL_FROM": SENDER,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def backend_with(handler: Handler, **overrides: Any) -> ResendEmailBackend:
    return ResendEmailBackend(resend_settings(**overrides), transport=httpx.MockTransport(handler))


def message(key: str | None = "agenthq-email-outbox-test") -> OutboundEmail:
    return OutboundEmail(
        to="recipient@example.com",
        subject="Verify your AgentHQ email",
        text_body=f"Open https://app.example.com/?auth=verify-email#token={SECRET_BODY_MARKER}",
        html_body=f'<a href="https://app.example.com/#token={SECRET_BODY_MARKER}">Verify</a>',
        idempotency_key=key,
    )


def error_response(status: int, name: str | None, message_text: str = "") -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        body: dict[str, Any] = {"statusCode": status, "message": message_text}
        if name is not None:
            body["name"] = name
        return httpx.Response(status, json=body, headers={"retry-after": "1"})

    return handler


def failure(backend: ResendEmailBackend) -> EmailDeliveryError:
    with pytest.raises(EmailDeliveryError) as raised:
        backend.send(message())
    return raised.value


def assert_clean_logs(text: str) -> None:
    assert API_KEY not in text
    assert SECRET_BODY_MARKER not in text
    assert "recipient@example.com" not in text


# --- Request contract ---------------------------------------------------------------------------


def test_successful_delivery_builds_the_documented_request(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeResend()
    with caplog.at_level(logging.DEBUG):
        assert backend_with(fake).send(message()) is True

    [request] = fake.requests
    assert request.method == "POST"
    assert str(request.url) == RESEND_API_URL == "https://api.resend.com/emails"
    assert request.url.scheme == "https"
    assert request.headers["Authorization"] == f"Bearer {API_KEY}"
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["User-Agent"].startswith("AgentHQ-Email/")
    assert request.headers["Idempotency-Key"] == "agenthq-email-outbox-test"
    assert fake.payload() == {
        "from": SENDER,
        "to": ["recipient@example.com"],
        "subject": "Verify your AgentHQ email",
        "html": message().html_body,
        "text": message().text_body,
    }
    assert "resend_email_accepted" in caplog.text and "provider_id=email-1" in caplog.text
    assert_clean_logs(caplog.text)


def test_message_without_idempotency_key_sends_no_header() -> None:
    fake = FakeResend()
    backend_with(fake).send(message(key=None))
    assert "Idempotency-Key" not in fake.requests[0].headers


def test_api_key_is_not_exposed_by_repr_or_settings() -> None:
    settings = resend_settings()
    backend = ResendEmailBackend(settings)

    assert API_KEY not in repr(backend)
    assert API_KEY not in repr(settings)
    assert API_KEY not in str(settings.model_dump())
    assert settings.resend_api_key is not None
    assert settings.resend_api_key.get_secret_value() == API_KEY


def test_redirects_are_never_followed() -> None:
    def redirect(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.resend.com":
            return httpx.Response(307, headers={"location": "https://attacker.example/steal"})
        raise AssertionError("followed a redirect, leaking the Authorization header")

    error = failure(backend_with(redirect))
    assert (error.reason, error.permanent) == ("provider_unexpected_status", False)


def test_timeout_is_bounded_and_configurable() -> None:
    seen: list[dict[str, float | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions["timeout"])
        return httpx.Response(200, json={"id": "email-1"})

    backend_with(handler, RESEND_TIMEOUT_SECONDS="4.5").send(message())
    assert seen == [{"connect": 4.5, "read": 4.5, "write": 4.5, "pool": 4.5}]


# --- Failure classification ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (httpx.ReadTimeout("read timed out"), "provider_timeout"),
        (httpx.ConnectTimeout("connect timed out"), "provider_timeout"),
        (httpx.ConnectError("connection refused"), "provider_network_error"),
        (httpx.RemoteProtocolError("peer closed"), "provider_network_error"),
    ],
)
def test_transport_failures_are_transient_and_unchained(
    exc: httpx.HTTPError,
    reason: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    with caplog.at_level(logging.DEBUG):
        error = failure(backend_with(handler))

    assert (error.reason, error.permanent) == (reason, False)
    assert str(error) == "Email delivery failed."
    # No chained httpx exception: its request object carries the Authorization header.
    assert error.__cause__ is None and error.__context__ is None
    assert_clean_logs(caplog.text)


@pytest.mark.parametrize(
    ("status", "name", "reason", "permanent"),
    [
        (401, "missing_api_key", "provider_auth_rejected", False),
        (401, "validation_error", "provider_auth_rejected", False),
        (403, "restricted_api_key", "provider_forbidden", False),
        (403, "validation_error", "provider_forbidden", False),
        (429, "rate_limit_exceeded", "provider_rate_limited", False),
        (429, "daily_quota_exceeded", "provider_daily_quota_exceeded", False),
        (429, "monthly_quota_exceeded", "provider_monthly_quota_exceeded", False),
        (400, "validation_error", "provider_rejected_request", True),
        (400, "invalid_idempotency_key", "provider_rejected_request", True),
        (422, "missing_required_field", "provider_rejected_request", True),
        (404, "not_found", "provider_endpoint_error", True),
        (405, "method_not_allowed", "provider_endpoint_error", True),
        (409, "concurrent_idempotent_requests", "provider_idempotency_in_progress", False),
        (409, "invalid_idempotent_request", "provider_idempotency_conflict", True),
        (408, None, "provider_timeout", False),
        (500, "application_error", "provider_unavailable", False),
        (503, "service_unavailable", "provider_unavailable", False),
        (418, None, "provider_unexpected_status", False),
    ],
)
def test_provider_errors_are_classified(
    status: int,
    name: str | None,
    reason: str,
    permanent: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    detail = "You can only send testing emails to your own email address (recipient@example.com)"
    with caplog.at_level(logging.DEBUG):
        error = failure(backend_with(error_response(status, name, detail)))

    assert (error.reason, error.permanent) == (reason, permanent)
    assert classify_resend_error(status, name) == (reason, permanent)
    assert f"status={status}" in caplog.text
    assert "You can only send" not in caplog.text  # provider message is never logged
    assert_clean_logs(caplog.text)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"<html>gateway</html>"),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"id": ""}),
        httpx.Response(200, json={"id": 42}),
        httpx.Response(200, json=["email-1"]),
        httpx.Response(200, json={"id": "x" * 500}),
    ],
)
def test_malformed_success_is_a_transient_failure_not_a_delivery(response: httpx.Response) -> None:
    error = failure(backend_with(lambda request: response))
    assert (error.reason, error.permanent) == ("provider_malformed_response", False)


def test_unexpected_error_name_and_non_json_error_bodies_are_not_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        failure(backend_with(error_response(500, "evil\nINJECTED log_line=1")))
        failure(
            backend_with(
                lambda request: httpx.Response(502, content=b"Bad gateway: " + API_KEY.encode())
            )
        )

    assert "INJECTED" not in caplog.text
    assert "error_name=None" in caplog.text
    assert_clean_logs(caplog.text)


def test_delivery_error_reason_is_restricted_to_safe_codes() -> None:
    assert EmailDeliveryError(reason="provider_rate_limited").reason == "provider_rate_limited"
    assert EmailDeliveryError(reason="leak recipient@example.com").reason == "delivery_failed"
    assert EmailDeliveryError(reason="x" * 65).reason == "delivery_failed"
    assert EmailDeliveryError().permanent is False


# --- Configuration ------------------------------------------------------------------------------


def test_backend_factory_selects_resend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAIL_BACKEND", "resend")
    monkeypatch.setenv("RESEND_API_KEY", API_KEY)
    monkeypatch.setenv("EMAIL_FROM", SENDER)
    get_settings.cache_clear()
    reset_email_backend()
    try:
        assert isinstance(get_email_backend(), ResendEmailBackend)
    finally:
        get_settings.cache_clear()
        reset_email_backend()


@pytest.mark.parametrize("key", [None, "", "   "])
def test_resend_requires_an_api_key(key: str | None) -> None:
    overrides: dict[str, Any] = {"RESEND_API_KEY": key}
    with pytest.raises(ValidationError, match="RESEND_API_KEY is required"):
        resend_settings(**overrides)


@pytest.mark.parametrize("key", ["re_abc def", "re_abc\ndef", "re_abc\tdef"])
def test_resend_rejects_malformed_api_keys(key: str) -> None:
    with pytest.raises(ValidationError, match="single API key value"):
        resend_settings(RESEND_API_KEY=key)


def test_resend_key_is_trimmed() -> None:
    settings = resend_settings(RESEND_API_KEY=f"  {API_KEY}  ")
    assert settings.resend_api_key is not None
    assert settings.resend_api_key.get_secret_value() == API_KEY


@pytest.mark.parametrize(
    "sender",
    [
        "",
        "not-an-address",
        "AgentHQ <>",
        "AgentHQ <no-reply@>",
        "a@example.com\r\nBcc: x@evil.test",
    ],
)
def test_resend_requires_a_valid_sender(sender: str) -> None:
    with pytest.raises(ValidationError, match="EMAIL_FROM"):
        resend_settings(EMAIL_FROM=sender)


def test_resend_needs_no_smtp_settings() -> None:
    settings = resend_settings()
    assert settings.smtp_host is None
    assert settings.smtp_username is None and settings.smtp_password is None


def production(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "production",
        "JWT_SECRET_KEY": "A-strong-production-secret-with-32-characters!",
        "FRONTEND_BASE_URL": "https://staging.agenthq.example.com",
    }
    values.update(overrides)
    return resend_settings(**values)


def test_production_resend_accepts_a_public_https_frontend() -> None:
    assert production().email_backend == "resend"


@pytest.mark.parametrize(
    "frontend_url",
    ["http://staging.agenthq.example.com", "https://localhost:5173", "https://127.0.0.1"],
)
def test_production_resend_requires_public_https_frontend(frontend_url: str) -> None:
    with pytest.raises(ValidationError, match="FRONTEND_BASE_URL"):
        production(FRONTEND_BASE_URL=frontend_url)


@pytest.mark.parametrize("sender", ["AgentHQ <no-reply@agenthq.local>", "no-reply@localhost"])
def test_production_resend_rejects_development_senders(sender: str) -> None:
    with pytest.raises(ValidationError, match="verified in Resend"):
        production(EMAIL_FROM=sender)


def test_configuration_errors_never_echo_secret_values() -> None:
    with pytest.raises(ValidationError) as raised:
        production(
            EMAIL_FROM="broken",
            DATABASE_URL="postgresql://agenthq:DbPasswordValue99@db.example.com/agenthq",
        )
    text = str(raised.value)
    assert API_KEY not in text
    assert "DbPasswordValue99" not in text
    assert "A-strong-production-secret" not in text


# --- Through the transactional outbox -----------------------------------------------------------


def install_resend(client: TestClient, fake: FakeResend) -> ResendEmailBackend:
    """Use the real Resend backend (mocked transport) for both delivery decisions and sends."""
    backend = ResendEmailBackend(resend_settings(), transport=httpx.MockTransport(fake))
    client.app.dependency_overrides[get_email_backend] = lambda: backend  # type: ignore[attr-defined]
    return backend


def bootstrap(client: TestClient) -> str:
    response = client.post(
        "/api/v1/organizations/bootstrap",
        json={
            "organization_name": "Resend Bank",
            "admin_full_name": "Resend Admin",
            "admin_email": ADMIN_EMAIL,
            "admin_password": ADMIN_PASSWORD,
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["access_token"])


def only_row(client: TestClient) -> EmailOutbox:
    with database_session(client) as db:
        rows = list(db.scalars(select(EmailOutbox)).all())
        assert len(rows) == 1
        db.expunge(rows[0])
        return rows[0]


def make_due(client: TestClient) -> None:
    with database_session(client) as db:
        for row in db.scalars(select(EmailOutbox)).all():
            if row.status == EmailOutboxStatus.PENDING:
                row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()


def meta(audit: AuditLog) -> dict[str, object]:
    assert audit.event_metadata is not None
    return audit.event_metadata


def audits(client: TestClient, action: str) -> list[AuditLog]:
    with database_session(client) as db:
        rows = list(db.scalars(select(AuditLog).where(AuditLog.action == action)).all())
        for row in rows:
            db.expunge(row)
        return rows


def test_verification_email_delivered_through_resend_end_to_end(
    unauthenticated_client: TestClient,
) -> None:
    fake = FakeResend()
    backend = install_resend(unauthenticated_client, fake)
    access = bootstrap(unauthenticated_client)
    assert fake.requests == []  # nothing is sent inside the HTTP request

    assert deliver_outbox(unauthenticated_client, backend) == 1
    row = only_row(unauthenticated_client)
    assert row.status == EmailOutboxStatus.SENT and row.token_nonce is None
    [request] = fake.requests
    assert request.headers["Idempotency-Key"] == email_outbox.idempotency_key(row.id)
    sent = fake.payload()
    assert sent["to"] == [ADMIN_EMAIL] and sent["from"] == SENDER
    assert "#token=" in sent["text"] and "#token=" in sent["html"]
    [audit] = audits(unauthenticated_client, "auth.email_verification_sent")
    assert meta(audit)["final"] is True and "error" not in meta(audit)

    token = raw_token_from_message(sent["text"])
    assert (
        unauthenticated_client.post("/api/v1/auth/verify-email", json={"token": token}).status_code
        == 200
    )
    me = unauthenticated_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"}
    )
    assert me.json()["email_verified"] is True
    assert deliver_outbox(unauthenticated_client, backend) == 0
    assert len(fake.requests) == 1


def test_transient_failure_retries_with_the_same_key_then_delivers(
    unauthenticated_client: TestClient,
) -> None:
    def flaky(request: httpx.Request, attempt: int) -> httpx.Response:
        if attempt == 1:
            return httpx.Response(503, json={"name": "service_unavailable", "message": "down"})
        return fake.accept(request)

    fake = FakeResend(flaky)
    backend = install_resend(unauthenticated_client, fake)
    bootstrap(unauthenticated_client)

    deliver_outbox(unauthenticated_client, backend)
    row = only_row(unauthenticated_client)
    assert row.status == EmailOutboxStatus.PENDING
    assert (row.attempts, row.last_error) == (1, "provider_unavailable")
    assert row.token_nonce is not None
    [failed] = audits(unauthenticated_client, "auth.email_verification_failed")
    assert meta(failed)["error"] == "provider_unavailable"
    assert meta(failed)["final"] is False
    assert deliver_outbox(unauthenticated_client, backend) == 0  # backoff respected

    make_due(unauthenticated_client)
    deliver_outbox(unauthenticated_client, backend)
    row = only_row(unauthenticated_client)
    assert row.status == EmailOutboxStatus.SENT and row.attempts == 2
    keys = {request.headers["Idempotency-Key"] for request in fake.requests}
    assert keys == {email_outbox.idempotency_key(row.id)}
    assert fake.payload(0) == fake.payload(1)  # identical body, so the key stays valid
    assert fake.unique_deliveries == 1


def test_ambiguous_outcome_is_retried_without_a_second_email(
    unauthenticated_client: TestClient,
) -> None:
    """Resend accepted the email but the response was unusable: retry, but no duplicate."""

    def accepted_then_garbled(request: httpx.Request, attempt: int) -> httpx.Response:
        accepted = fake.accept(request)
        if attempt == 1:
            return httpx.Response(200, content=b"upstream proxy error")
        return accepted

    fake = FakeResend(accepted_then_garbled)
    backend = install_resend(unauthenticated_client, fake)
    bootstrap(unauthenticated_client)

    deliver_outbox(unauthenticated_client, backend)
    assert only_row(unauthenticated_client).last_error == "provider_malformed_response"
    make_due(unauthenticated_client)
    deliver_outbox(unauthenticated_client, backend)

    assert only_row(unauthenticated_client).status == EmailOutboxStatus.SENT
    assert len(fake.requests) == 2
    assert fake.unique_deliveries == 1


def test_expired_lease_after_a_crash_does_not_send_twice(
    unauthenticated_client: TestClient,
) -> None:
    """A worker was claimed, Resend accepted, then the process died before recording SENT."""
    fake = FakeResend()
    backend = install_resend(unauthenticated_client, fake)
    bootstrap(unauthenticated_client)

    with database_session(unauthenticated_client) as db:
        [claimed] = email_outbox.claim_due(db)
    row = only_row(unauthenticated_client)
    backend.send(
        OutboundEmail(
            to=ADMIN_EMAIL,
            subject="Verify your AgentHQ email",
            text_body="first copy",
            html_body="<p>first copy</p>",
            idempotency_key=email_outbox.idempotency_key(claimed),
        )
    )
    assert row.status == EmailOutboxStatus.SENDING  # crash: status never updated

    assert deliver_outbox(unauthenticated_client, backend) == 0  # lease still held
    with database_session(unauthenticated_client) as db:
        held = db.get(EmailOutbox, claimed)
        assert held is not None
        held.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert deliver_outbox(unauthenticated_client, backend) == 1

    assert only_row(unauthenticated_client).status == EmailOutboxStatus.SENT
    assert len(fake.requests) == 2
    assert fake.unique_deliveries == 1


def test_permanent_rejection_fails_the_row_immediately(
    unauthenticated_client: TestClient,
) -> None:
    fake = FakeResend(
        lambda request, attempt: httpx.Response(
            422, json={"name": "missing_required_field", "message": f"to: {ADMIN_EMAIL}"}
        )
    )
    backend = install_resend(unauthenticated_client, fake)
    bootstrap(unauthenticated_client)

    deliver_outbox(unauthenticated_client, backend)
    row = only_row(unauthenticated_client)
    assert row.status == EmailOutboxStatus.FAILED
    assert (row.attempts, row.last_error, row.token_nonce) == (1, "provider_rejected_request", None)
    [failed] = audits(unauthenticated_client, "auth.email_verification_failed")
    assert meta(failed)["final"] is True
    assert ADMIN_EMAIL not in json.dumps(meta(failed))
    make_due(unauthenticated_client)
    assert deliver_outbox(unauthenticated_client, backend) == 0
    assert len(fake.requests) == 1


def test_transient_failures_stop_at_max_attempts(
    unauthenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMAIL_OUTBOX_MAX_ATTEMPTS", "3")
    get_settings.cache_clear()
    fake = FakeResend(
        lambda request, attempt: httpx.Response(429, json={"name": "rate_limit_exceeded"})
    )
    backend = install_resend(unauthenticated_client, fake)
    bootstrap(unauthenticated_client)

    for _ in range(3):
        make_due(unauthenticated_client)
        deliver_outbox(unauthenticated_client, backend)

    row = only_row(unauthenticated_client)
    assert row.status == EmailOutboxStatus.FAILED
    assert (row.attempts, row.last_error, row.token_nonce) == (3, "provider_rate_limited", None)
    finals = [
        meta(a)["final"] for a in audits(unauthenticated_client, "auth.email_verification_failed")
    ]
    assert finals == [False, False, True]
    make_due(unauthenticated_client)
    assert deliver_outbox(unauthenticated_client, backend) == 0
    assert len(fake.requests) == 3


def test_password_reset_and_invite_emails_are_delivered_through_resend(
    unauthenticated_client: TestClient,
) -> None:
    capture = capture_email(unauthenticated_client)
    access = bootstrap(unauthenticated_client)
    deliver_outbox(unauthenticated_client, capture)
    verify_link = raw_token_from_message(capture.messages[-1].text_body)
    assert (
        unauthenticated_client.post(
            "/api/v1/auth/verify-email", json={"token": verify_link}
        ).status_code
        == 200
    )

    fake = FakeResend()
    backend = install_resend(unauthenticated_client, fake)
    invite = unauthenticated_client.post(
        "/api/v1/organization-invites",
        headers={"Authorization": f"Bearer {access}"},
        json={"email": "invitee@example.com", "role": "auditor"},
    )
    assert invite.status_code == 201 and invite.json()["email_delivery"] == "queued"
    forgot = unauthenticated_client.post(
        "/api/v1/auth/forgot-password", json={"email": ADMIN_EMAIL}
    )
    assert forgot.status_code == 200
    assert deliver_outbox(unauthenticated_client, backend) == 2

    by_recipient = {fake.payload(i)["to"][0]: fake.payload(i) for i in range(len(fake.requests))}
    assert set(by_recipient) == {"invitee@example.com", ADMIN_EMAIL}
    assert "?auth=invite#token=" in by_recipient["invitee@example.com"]["text"]
    assert "?auth=reset-password#token=" in by_recipient[ADMIN_EMAIL]["text"]
    keys = [request.headers["Idempotency-Key"] for request in fake.requests]
    assert len(set(keys)) == 2 and all(k.startswith("agenthq-email-outbox-") for k in keys)

    reset_token = raw_token_from_message(by_recipient[ADMIN_EMAIL]["text"])
    reset = unauthenticated_client.post(
        "/api/v1/auth/reset-password",
        json={"token": reset_token, "new_password": "BrandNewResendPassword456!"},
    )
    assert reset.status_code == 200
    old_session = unauthenticated_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"}
    )
    assert old_session.status_code == 401
    with database_session(unauthenticated_client) as db:
        kinds = {row.kind: row.status for row in db.scalars(select(EmailOutbox)).all()}
    assert kinds[EmailOutboxKind.ORGANIZATION_INVITE] == EmailOutboxStatus.SENT
    assert kinds[EmailOutboxKind.PASSWORD_RESET] == EmailOutboxStatus.SENT


def test_outbox_and_audit_records_never_contain_provider_detail_or_secrets(
    unauthenticated_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeResend(
        lambda request, attempt: httpx.Response(
            403,
            json={"name": "validation_error", "message": f"Only {ADMIN_EMAIL} may receive tests"},
        )
    )
    backend = install_resend(unauthenticated_client, fake)
    bootstrap(unauthenticated_client)
    with caplog.at_level(logging.DEBUG):
        deliver_outbox(unauthenticated_client, backend)

    row = only_row(unauthenticated_client)
    assert row.last_error == "provider_forbidden" and row.status == EmailOutboxStatus.PENDING
    stored = json.dumps(
        [meta(a) for a in audits(unauthenticated_client, "auth.email_verification_failed")]
    )
    for text in (caplog.text, stored, row.last_error or ""):
        assert API_KEY not in text
        assert "may receive tests" not in text
        assert "#token=" not in text
    assert ADMIN_EMAIL not in caplog.text
