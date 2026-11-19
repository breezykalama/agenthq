"""PostgreSQL-only: concurrent outbox workers delivering through the Resend backend.

Opt-in, exactly like test_bootstrap_postgres.py: set AGENTHQ_TEST_POSTGRES_URL to a *disposable*
server's maintenance database. Databases are created and dropped here and are named
agenthq_outbox_*. All HTTP goes through httpx.MockTransport; no email is sent.
"""

import json
import os
import threading
import time
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.core.config import Settings, get_settings
from app.core.security import hash_password
from app.models.email_outbox import EmailOutbox, EmailOutboxStatus
from app.models.user import User
from app.services import email_outbox
from app.services import identity as identity_service
from app.services.email import ResendEmailBackend

ADMIN_URL = os.environ.get("AGENTHQ_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL, reason="set AGENTHQ_TEST_POSTGRES_URL to a disposable PostgreSQL server"
)
BACKEND = Path(__file__).parents[1]
WORKERS = 8
ROWS = 12


def admin_engine() -> Engine:
    assert ADMIN_URL is not None
    return create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")


def database_url(name: str) -> str:
    assert ADMIN_URL is not None
    return make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)


@pytest.fixture()
def pg() -> Iterator[sessionmaker[Session]]:
    name = f"agenthq_outbox_{uuid4().hex[:8]}"
    engine = admin_engine()
    with engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url(name)
    get_settings.cache_clear()
    try:
        config = Config()  # no ini: keeps fileConfig from disabling loggers (see bootstrap tests)
        config.set_main_option("script_location", str(BACKEND / "alembic"))
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()
    database = create_engine(database_url(name), pool_size=WORKERS + 4, max_overflow=0)

    @event.listens_for(database, "after_cursor_execute")
    def hold_claim(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        # Pause each worker after its claim query returns and before it marks rows SENDING.
        # Without row locks every worker would then see (and send) the same rows.
        if statement.lstrip().upper().startswith("SELECT") and "FROM email_outbox" in statement:
            if "ORDER BY email_outbox.next_attempt_at" in statement:
                time.sleep(0.2)

    try:
        yield sessionmaker(bind=database, autoflush=False)
    finally:
        database.dispose()
        with engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        engine.dispose()


class SlowFakeResend:
    """Thread-safe recorder. The delay widens the window in which a second worker could
    double-claim a row if SKIP LOCKED / leasing were broken."""

    def __init__(self) -> None:
        self.keys: Counter[str] = Counter()
        self.recipients: Counter[str] = Counter()
        self._lock = threading.Lock()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        time.sleep(0.05)
        key = request.headers["Idempotency-Key"]
        with self._lock:
            self.keys[key] += 1
            self.recipients[json.loads(request.content)["to"][0]] += 1
        return httpx.Response(200, json={"id": f"email-{key[-8:]}"})


def queue_verifications(pg: sessionmaker[Session]) -> list[str]:
    emails = [f"outbox-{i}@example.com" for i in range(ROWS)]
    with pg() as db:
        for email in emails:
            user = User(
                email=email,
                full_name="Outbox User",
                password_hash=hash_password("OutboxPassword123!"),
                role="auditor",
                email_verification_required=True,
            )
            db.add(user)
            db.flush()
            identity_service.queue_email_verification(db, user)
        db.commit()
    return emails


def test_concurrent_workers_submit_each_email_exactly_once(pg: sessionmaker[Session]) -> None:
    emails = queue_verifications(pg)
    fake = SlowFakeResend()
    backend = ResendEmailBackend(
        Settings(
            _env_file=None,
            DATABASE_URL="postgresql://unused:unused@localhost/unused",
            EMAIL_BACKEND="resend",
            RESEND_API_KEY="re_TestOnlyKey_concurrency",
            EMAIL_FROM="AgentHQ <no-reply@staging.example.com>",
        ),
        transport=httpx.MockTransport(fake),
    )
    barrier = threading.Barrier(WORKERS)
    processed: list[int] = []
    errors: list[str] = []
    guard = threading.Lock()

    def worker() -> None:
        total = 0
        try:
            with pg() as db:
                db.execute(text("SELECT 1"))  # connect before the race starts
                db.commit()
                barrier.wait()
                while (count := email_outbox.dispatch_due(db, backend)) > 0:
                    total += count
        except Exception as exc:  # recorded and asserted on below
            with guard:
                errors.append(type(exc).__name__)
        with guard:
            processed.append(total)

    threads = [threading.Thread(target=worker) for _ in range(WORKERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)

    assert errors == []
    assert sum(processed) == ROWS  # every row claimed by exactly one worker
    assert len(fake.keys) == ROWS and set(fake.keys.values()) == {1}
    assert fake.recipients == Counter(emails)
    with pg() as db:
        rows = list(db.scalars(select(EmailOutbox)).all())
        assert {row.status for row in rows} == {EmailOutboxStatus.SENT}
        assert {row.attempts for row in rows} == {1}
        assert all(row.token_nonce is None and row.lease_expires_at is None for row in rows)
        assert set(fake.keys) == {email_outbox.idempotency_key(row.id) for row in rows}
