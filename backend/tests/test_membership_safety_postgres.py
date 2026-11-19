"""PostgreSQL-only: concurrent invite acceptances for one person must yield one active membership.

Opt-in, exactly like test_bootstrap_postgres.py: set AGENTHQ_TEST_POSTGRES_URL to a *disposable*
server's maintenance database. Databases named agenthq_membership_* are created and dropped here.
"""

import os
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.core.config import get_settings
from app.core.security import hash_password
from app.models.organization import Organization, OrganizationMembership
from app.models.organization_invite import OrganizationInvite, OrganizationInviteStatus
from app.models.user import User, UserRole
from app.schemas.organization_invite import OrganizationInviteAccept
from app.services import organization_invites as invite_service

ADMIN_URL = os.environ.get("AGENTHQ_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL, reason="set AGENTHQ_TEST_POSTGRES_URL to a disposable PostgreSQL server"
)
BACKEND = Path(__file__).parents[1]
PASSWORD = "StrongPassword123!"
INVITEE = "invitee@example.com"


def admin_engine() -> Engine:
    assert ADMIN_URL is not None
    return create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")


def database_url(name: str) -> str:
    assert ADMIN_URL is not None
    return make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)


@pytest.fixture()
def pg(monkeypatch: pytest.MonkeyPatch) -> Iterator[sessionmaker[Session]]:
    name = f"agenthq_membership_{uuid4().hex[:8]}"
    engine = admin_engine()
    with engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    # accept_invite issues a JWT, which reads settings; point them at this database.
    monkeypatch.setenv("DATABASE_URL", database_url(name))
    get_settings.cache_clear()
    config = Config()  # no ini: keeps fileConfig from disabling loggers (see bootstrap tests)
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(config, "head")
    database = create_engine(database_url(name), pool_size=6, max_overflow=0)

    @event.listens_for(database, "after_cursor_execute")
    def hold_after_invite_lock(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        # Pause each acceptance right after it locks its invite row, so both requests reach the
        # membership check together. Without the user-row lock both would pass it.
        if "FROM organization_invites" in statement and "FOR UPDATE" in statement:
            time.sleep(0.3)

    try:
        yield sessionmaker(bind=database, autoflush=False)
    finally:
        database.dispose()
        get_settings.cache_clear()
        with engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        engine.dispose()


def seed(pg: sessionmaker[Session], *, invitee_exists: bool) -> dict[str, UUID]:
    """Two organizations, each with an admin and a pending invite for the same email."""
    tokens: dict[str, UUID] = {}
    with pg() as db:
        if invitee_exists:
            db.add(
                User(
                    email=INVITEE,
                    full_name="Invitee",
                    password_hash=hash_password(PASSWORD),
                    role=UserRole.AGENT_OWNER,
                )
            )
        for label in ("b", "c"):
            organization = Organization(name=f"Org {label}", slug=f"org-{label}")
            admin = User(
                email=f"admin-{label}@example.com",
                full_name=f"Admin {label}",
                password_hash=hash_password(PASSWORD),
                role=UserRole.ADMIN,
            )
            db.add_all([organization, admin])
            db.flush()
            db.add(
                OrganizationMembership(
                    organization_id=organization.id, user_id=admin.id, role=UserRole.ADMIN
                )
            )
            raw = f"phase0-race-token-{label}-{uuid4().hex}"
            invite = OrganizationInvite(
                organization_id=organization.id,
                email=INVITEE,
                full_name="Invitee",
                role=UserRole.AUDITOR,
                token_hash=invite_service.token_digest(raw),
                invited_by_user_id=admin.id,
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
            db.add(invite)
            db.flush()
            tokens[raw] = invite.id
        db.commit()
    return tokens


def race(pg: sessionmaker[Session], raw_tokens: list[str]) -> tuple[list[str], list[str]]:
    barrier = threading.Barrier(len(raw_tokens))
    successes: list[str] = []
    failures: list[str] = []
    guard = threading.Lock()

    def worker(raw: str) -> None:
        with pg() as db:
            db.execute(text("SELECT 1"))  # connect before the race starts
            db.commit()
            barrier.wait()
            try:
                invite_service.accept_invite(
                    db, OrganizationInviteAccept(token=raw, password=PASSWORD)
                )
                with guard:
                    successes.append(raw)
            except Exception as exc:  # recorded and asserted on below
                db.rollback()
                with guard:
                    failures.append(type(exc).__name__)

    threads = [threading.Thread(target=worker, args=(raw,)) for raw in raw_tokens]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return successes, failures


def active_memberships(db: Session) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(OrganizationMembership)
            .join(User, User.id == OrganizationMembership.user_id)
            .where(User.email == INVITEE, OrganizationMembership.is_active.is_(True))
        )
        or 0
    )


def assert_one_membership_and_loser_pending(
    pg: sessionmaker[Session], tokens: dict[str, UUID], successes: list[str]
) -> None:
    with pg() as db:
        assert active_memberships(db) == 1
        statuses = {
            raw: db.get(OrganizationInvite, invite_id).status  # type: ignore[union-attr]
            for raw, invite_id in tokens.items()
        }
    assert statuses[successes[0]] == OrganizationInviteStatus.ACCEPTED
    loser = next(raw for raw in tokens if raw != successes[0])
    assert statuses[loser] == OrganizationInviteStatus.PENDING


def test_concurrent_accepts_by_existing_user_create_one_membership(
    pg: sessionmaker[Session],
) -> None:
    tokens = seed(pg, invitee_exists=True)

    successes, failures = race(pg, list(tokens))

    assert len(successes) == 1
    assert failures == ["MultipleOrganizationsNotSupportedError"]
    assert_one_membership_and_loser_pending(pg, tokens, successes)


def test_concurrent_accepts_creating_a_new_user_create_one_membership(
    pg: sessionmaker[Session],
) -> None:
    # No account exists yet: the unique email constraint lets exactly one request create it.
    tokens = seed(pg, invitee_exists=False)

    successes, failures = race(pg, list(tokens))

    assert len(successes) == 1
    assert failures == ["DuplicateOrganizationMembershipError"]
    assert_one_membership_and_loser_pending(pg, tokens, successes)
    with pg() as db:
        assert db.scalar(select(func.count()).select_from(User).where(User.email == INVITEE)) == 1
