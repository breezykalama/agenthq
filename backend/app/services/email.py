import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from functools import lru_cache
from typing import Protocol

from app.core.config import Settings, get_settings
from app.core.rate_limit import safe_identifier

email_logger = logging.getLogger("agenthq.email")


class EmailDeliveryError(Exception):
    """Delivery failed. Messages are generic; provider details are never propagated."""


@dataclass(frozen=True)
class OutboundEmail:
    to: str
    subject: str
    text_body: str
    html_body: str


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


@lru_cache
def get_email_backend() -> EmailBackend:
    settings = get_settings()
    if settings.email_backend == "smtp":
        return SMTPEmailBackend(settings)
    if settings.email_backend == "disabled":
        return DisabledEmailBackend()
    if settings.is_production:
        return DisabledEmailBackend()
    return ConsoleEmailBackend()


def reset_email_backend() -> None:
    get_email_backend.cache_clear()
