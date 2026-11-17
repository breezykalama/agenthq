import re
from collections.abc import Callable, Iterator
from typing import cast
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services import email_outbox
from app.services.email import ConsoleEmailBackend, EmailBackend, get_email_backend


def capture_email(client: TestClient) -> ConsoleEmailBackend:
    backend = ConsoleEmailBackend()
    app = cast(FastAPI, client.app)
    app.dependency_overrides[get_email_backend] = lambda: backend
    return backend


def database_session(client: TestClient) -> Session:
    app = cast(FastAPI, client.app)
    override = cast(Callable[[], Iterator[Session]], app.dependency_overrides[get_db])
    return next(override())


def current_backend(client: TestClient) -> EmailBackend:
    app = cast(FastAPI, client.app)
    factory = app.dependency_overrides.get(get_email_backend, get_email_backend)
    return cast(EmailBackend, factory())


def deliver_outbox(client: TestClient, backend: EmailBackend | None = None) -> int:
    """Run one outbox dispatch pass, as the background worker would after commit."""
    with database_session(client) as db:
        return email_outbox.dispatch_due(db, backend or current_backend(client))


def raw_token_from_message(body: str) -> str:
    match = re.search(r"https?://\S+", body)
    assert match is not None
    parts = urlsplit(match.group(0))
    assert "token" not in parse_qs(parts.query), "tokens must not travel in the query string"
    return parse_qs(parts.fragment)["token"][0]


def verify_pending_admin(client: TestClient) -> None:
    """Deliver queued verification email and complete verification, as a bootstrapped
    administrator must before using organization features."""
    backend = ConsoleEmailBackend()
    deliver_outbox(client, backend)
    links = [m for m in backend.messages if "verify-email" in m.text_body]
    assert links, "expected a queued verification email"
    token = raw_token_from_message(links[-1].text_body)
    response = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert response.status_code == 200, response.text
