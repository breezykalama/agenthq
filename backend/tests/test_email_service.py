import logging
import smtplib
from email.message import EmailMessage

import pytest

from app.core.config import Settings
from app.services.email import (
    ConsoleEmailBackend,
    DisabledEmailBackend,
    EmailDeliveryError,
    OutboundEmail,
    SMTPEmailBackend,
)


def message() -> OutboundEmail:
    return OutboundEmail(
        to="operator@example.com",
        subject="AgentHQ test",
        text_body="Test message",
        html_body="<p>Test message</p>",
    )


def settings() -> Settings:
    return Settings(
        _env_file=None,
        DATABASE_URL="postgresql://agenthq:agenthq@localhost:5432/agenthq",
        EMAIL_BACKEND="smtp",
        SMTP_HOST="smtp.example.com",
        SMTP_USERNAME="agenthq",
        SMTP_PASSWORD="smtp-super-secret",
    )


def test_console_backend_captures_email(caplog: pytest.LogCaptureFixture) -> None:
    backend = ConsoleEmailBackend()

    with caplog.at_level(logging.INFO, logger="agenthq.email"):
        delivered = backend.send(message())

    assert delivered is True
    assert backend.messages == [message()]
    assert "Test message" in caplog.text


def test_disabled_backend_is_safe_noop() -> None:
    assert DisabledEmailBackend().send(message()) is False


def test_smtp_backend_does_not_log_password(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            self.host = host

        def __enter__(self) -> "FakeSMTP":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def starttls(self) -> None:
            return None

        def login(self, username: str, password: str) -> None:
            assert username == "agenthq"
            assert password == "smtp-super-secret"

        def send_message(self, email: EmailMessage) -> None:
            assert email["To"] == "operator@example.com"

    monkeypatch.setattr("app.services.email.smtplib.SMTP", FakeSMTP)

    with caplog.at_level(logging.INFO, logger="agenthq.email"):
        assert SMTPEmailBackend(settings()).send(message()) is True

    assert "smtp-super-secret" not in caplog.text


def test_smtp_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class RefusingSMTP:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            assert timeout == 10.0

        def __enter__(self) -> "RefusingSMTP":
            raise smtplib.SMTPRecipientsRefused(
                {"operator@example.com": (550, b"mailbox operator@example.com unknown")}
            )

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr("app.services.email.smtplib.SMTP", RefusingSMTP)

    with caplog.at_level(logging.INFO, logger="agenthq.email"):
        with pytest.raises(EmailDeliveryError) as raised:
            SMTPEmailBackend(settings()).send(message())

    assert str(raised.value) == "Email delivery failed."
    assert raised.value.__cause__ is None
    assert "operator@example.com" not in caplog.text
    assert "SMTPRecipientsRefused" in caplog.text


def test_smtp_ssl_mode_uses_implicit_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeSSL:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            calls.append(f"ssl:{port}:{timeout}")

        def __enter__(self) -> "FakeSSL":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def starttls(self) -> None:
            raise AssertionError("STARTTLS must not run on an implicit TLS connection")

        def login(self, username: str, password: str) -> None:
            calls.append("login")

        def send_message(self, email: EmailMessage) -> None:
            calls.append("send")

    monkeypatch.setattr("app.services.email.smtplib.SMTP_SSL", FakeSSL)
    ssl_settings = settings().model_copy(
        update={
            "smtp_use_ssl": True,
            "smtp_use_tls": False,
            "smtp_port": 465,
            "smtp_timeout_seconds": 5.0,
        }
    )

    assert SMTPEmailBackend(ssl_settings).send(message()) is True
    assert calls == ["ssl:465:5.0", "login", "send"]


def test_disabled_backend_does_not_log_recipient(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="agenthq.email"):
        DisabledEmailBackend().send(message())

    assert "operator@example.com" not in caplog.text
