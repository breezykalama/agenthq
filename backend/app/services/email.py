import logging
import re
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from functools import lru_cache
from typing import Protocol

import httpx

from app.core.config import Settings, get_settings
from app.core.rate_limit import safe_identifier

email_logger = logging.getLogger("agenthq.email")


SAFE_REASON_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}")


class EmailDeliveryError(Exception):
    """Delivery failed. Messages are generic; provider details are never propagated.

    ``reason`` is a short fixed code stored in the outbox and audit log. ``permanent`` means
    retrying the same message cannot succeed, so the outbox stops instead of backing off.
    """

    def __init__(
        self,
        message: str = "Email delivery failed.",
        *,
        reason: str = "delivery_failed",
        permanent: bool = False,
    ) -> None:
        super().__init__(message)
        self.reason = reason if SAFE_REASON_PATTERN.fullmatch(reason) else "delivery_failed"
        self.permanent = permanent


@dataclass(frozen=True)
class OutboundEmail:
    to: str
    subject: str
    text_body: str
    html_body: str
    # Stable per outbox row, so a provider that supports idempotency can drop a re-send.
    idempotency_key: str | None = None


class EmailBackend(Protocol):
    def send(self, message: OutboundEmail) -> bool: ...


def delivery_enabled(backend: EmailBackend) -> bool:
    """Whether a backend can deliver at all (the disabled backend cannot)."""
    return bool(getattr(backend, "enabled", True))


class ConsoleEmailBackend:
    """Local development only. Logs the full message, including links, to the console."""

    enabled = True

    def __init__(self) -> None:
        self.messages: list[OutboundEmail] = []

    def send(self, message: OutboundEmail) -> bool:
        self.messages.append(message)
        email_logger.info(
            "console_email recipient=%s subject=%s\n%s",
            message.to,
            message.subject,
            message.text_body,
        )
        return True


class DisabledEmailBackend:
    enabled = False

    def send(self, message: OutboundEmail) -> bool:
        email_logger.info(
            "email_delivery_disabled recipient_hash=%s", safe_identifier(message.to)
        )
        return False


class SMTPEmailBackend:
    enabled = True

    def __init__(self, settings: Settings) -> None:
        if settings.smtp_host is None:
            raise EmailDeliveryError("SMTP email is not configured.")
        self.settings = settings
        self.smtp_host = settings.smtp_host

    def _connect(self) -> smtplib.SMTP:
        if self.settings.smtp_use_ssl:
            return smtplib.SMTP_SSL(
                self.smtp_host,
                self.settings.smtp_port,
                timeout=self.settings.smtp_timeout_seconds,
            )
        return smtplib.SMTP(
            self.smtp_host,
            self.settings.smtp_port,
            timeout=self.settings.smtp_timeout_seconds,
        )

    def send(self, message: OutboundEmail) -> bool:
        email = EmailMessage()
        email["From"] = self.settings.email_from
        email["To"] = message.to
        email["Subject"] = message.subject
        email.set_content(message.text_body)
        email.add_alternative(message.html_body, subtype="html")
        try:
            with self._connect() as client:
                if self.settings.smtp_use_tls:
                    client.starttls()
                if self.settings.smtp_username and self.settings.smtp_password:
                    client.login(self.settings.smtp_username, self.settings.smtp_password)
                client.send_message(email)
        except (OSError, smtplib.SMTPException) as exc:
            # Only the exception class is logged: provider responses can echo addresses,
            # credentials hints, or message content.
            email_logger.warning(
                "smtp_email_delivery_failed recipient_hash=%s error_type=%s",
                safe_identifier(message.to),
                type(exc).__name__,
            )
            raise EmailDeliveryError("Email delivery failed.") from None
        return True


RESEND_API_URL = "https://api.resend.com/emails"
RESEND_USER_AGENT = "AgentHQ-Email/1.0"
RESEND_ERROR_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,47}")
RESEND_MAX_PROVIDER_ID_LENGTH = 128


@dataclass(frozen=True)
class _ResendFailure:
    reason: str
    permanent: bool
    status: int | None = None
    error_name: str | None = None


def _resend_error_name(response: httpx.Response) -> str | None:
    """The documented error ``name`` (e.g. ``rate_limit_exceeded``), only if it looks like one.
    The ``message`` field is never read: it can echo addresses or account details."""
    try:
        body = response.json()
    except ValueError:
        return None
    name = body.get("name") if isinstance(body, dict) else None
    if isinstance(name, str) and RESEND_ERROR_NAME_PATTERN.fullmatch(name):
        return name
    return None


def classify_resend_error(status: int, error_name: str | None) -> tuple[str, bool]:
    """Map a Resend error response to (reason code, permanent).

    Permanent: the request itself is invalid (400/422), the endpoint is wrong (404/405), or an
    idempotency key was reused with a different payload; resending the same payload cannot help.
    Everything else is retried within the outbox's bounded schedule, including 401/403, which
    on the send endpoint mean a missing, invalid, restricted or suspended key or an unverified
    sending domain: operator-fixable configuration, so a fix during the backoff window still
    delivers.
    """
    if status == 429:
        if error_name == "daily_quota_exceeded":
            return "provider_daily_quota_exceeded", False
        if error_name == "monthly_quota_exceeded":
            return "provider_monthly_quota_exceeded", False
        return "provider_rate_limited", False
    if status == 409:
        if error_name == "concurrent_idempotent_requests":
            return "provider_idempotency_in_progress", False
        return "provider_idempotency_conflict", True
    if status == 401:
        return "provider_auth_rejected", False
    if status == 403:
        return "provider_forbidden", False
    if status in {400, 422}:
        return "provider_rejected_request", True
    if status in {404, 405}:
        return "provider_endpoint_error", True
    if status == 408:
        return "provider_timeout", False
    if status >= 500:
        return "provider_unavailable", False
    return "provider_unexpected_status", False


class ResendEmailBackend:
    """Resend HTTPS API (https://resend.com/docs/api-reference/emails/send-email).

    One bounded POST per message, no redirects, HTTPS only. The outbox row id is sent as the
    ``Idempotency-Key``, which Resend keeps for 24 hours, so a retry after an ambiguous outcome
    (timeout, crash after acceptance, malformed response) does not send a second email.
    """

    enabled = True

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        key = settings.resend_api_key.get_secret_value().strip() if settings.resend_api_key else ""
        if not key:
            raise EmailDeliveryError("Resend email is not configured.")
        self._api_key = key
        self._sender = settings.email_from
        self._timeout = settings.resend_timeout_seconds
        self._transport = transport

    def __repr__(self) -> str:
        return "ResendEmailBackend()"

    def _headers(self, message: OutboundEmail) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": RESEND_USER_AGENT,
        }
        if message.idempotency_key:
            headers["Idempotency-Key"] = message.idempotency_key
        return headers

    def _post(self, message: OutboundEmail) -> httpx.Response | _ResendFailure:
        payload = {
            "from": self._sender,
            "to": [message.to],
            "subject": message.subject,
            "html": message.html_body,
            "text": message.text_body,
        }
        try:
            with httpx.Client(
                timeout=httpx.Timeout(self._timeout),
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                return client.post(RESEND_API_URL, json=payload, headers=self._headers(message))
        except httpx.TimeoutException:
            return _ResendFailure("provider_timeout", permanent=False)
        except httpx.HTTPError:
            return _ResendFailure("provider_network_error", permanent=False)

    def send(self, message: OutboundEmail) -> bool:
        outcome = self._post(message)
        failure: _ResendFailure | None = None
        provider_id: str | None = None
        if isinstance(outcome, _ResendFailure):
            failure = outcome
        elif 200 <= outcome.status_code < 300:
            try:
                body = outcome.json()
            except ValueError:
                body = None
            candidate = body.get("id") if isinstance(body, dict) else None
            if (
                isinstance(candidate, str)
                and candidate.strip()
                and len(candidate) <= RESEND_MAX_PROVIDER_ID_LENGTH
            ):
                provider_id = candidate
            else:
                # Possibly accepted; retrying with the same idempotency key is safe.
                failure = _ResendFailure(
                    "provider_malformed_response", permanent=False, status=outcome.status_code
                )
        else:
            error_name = _resend_error_name(outcome)
            reason, permanent = classify_resend_error(outcome.status_code, error_name)
            failure = _ResendFailure(reason, permanent, outcome.status_code, error_name)

        if failure is not None:
            # Raised outside every ``except`` block, so no httpx exception (whose request holds
            # the Authorization header) is chained to the error as cause or context.
            email_logger.warning(
                "resend_email_delivery_failed recipient_hash=%s reason=%s permanent=%s "
                "status=%s error_name=%s",
                safe_identifier(message.to),
                failure.reason,
                failure.permanent,
                failure.status,
                failure.error_name,
            )
            raise EmailDeliveryError(
                "Email delivery failed.", reason=failure.reason, permanent=failure.permanent
            )
        email_logger.info(
            "resend_email_accepted recipient_hash=%s provider_id=%s",
            safe_identifier(message.to),
            provider_id,
        )
        return True


@lru_cache
def get_email_backend() -> EmailBackend:
    settings = get_settings()
    if settings.email_backend == "smtp":
        return SMTPEmailBackend(settings)
    if settings.email_backend == "resend":
        return ResendEmailBackend(settings)
    if settings.email_backend == "disabled":
        return DisabledEmailBackend()
    if settings.is_production:
        return DisabledEmailBackend()
    return ConsoleEmailBackend()


def reset_email_backend() -> None:
    get_email_backend.cache_clear()
