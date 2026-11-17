"""PostgreSQL-only bootstrap tests against a database built by the real Alembic chain.

Opt-in: set AGENTHQ_TEST_POSTGRES_URL to a *disposable* server's maintenance database, e.g.
postgresql+psycopg://user:pass@127.0.0.1:55434/postgres. Each test gets its own database,
cloned from a migrated template; all databases are created and dropped by these tests and
are named agenthq_bootstrap_*. Skipped when the variable is unset.
"""

import os
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.core.config import get_settings
from app.core.tenancy import PLACEHOLDER_ORGANIZATION_SLUG, get_current_organization_id
from app.db.base import Base
from app.db.session import get_db
from app.models.email_outbox import EmailOutbox
from app.models.identity_token import EmailVerificationToken
from app.models.organization import Organization, OrganizationMembership
from app.models.user import User
from app.schemas.organization import OrganizationBootstrapRequest
from app.schemas.user import UserRegister
from app.services import identity as identity_service
from app.services import organizations as organization_service
from app.services import users as user_service
from app.services.email import ConsoleEmailBackend, get_email_backend

ADMIN_URL = os.environ.get("AGENTHQ_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL, reason="set AGENTHQ_TEST_POSTGRES_URL to a disposable PostgreSQL server"
)
BACKEND = Path(__file__).parents[1]


def admin_engine() -> Engine:
    assert ADMIN_URL is not None
    return create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")


def database_url(name: str) -> str:
    assert ADMIN_URL is not None
    return make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)


@pytest.fixture(scope="module")
def template_database() -> Iterator[str]:
    name = f"agenthq_bootstrap_tpl_{uuid4().hex[:8]}"
    engine = admin_engine()
    with engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url(name)
    get_settings.cache_clear()
    try:
        # No ini file on purpose: env.py then skips logging.config.fileConfig, which would
        # otherwise disable every existing logger and break caplog in later tests.
        config = Config()
        config.set_main_option("script_location", str(BACKEND / "alembic"))
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()
    yield name
    with engine.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    engine.dispose()


@pytest.fixture()
def pg(template_database: str) -> Iterator[sessionmaker[Session]]:
    name = f"agenthq_bootstrap_{uuid4().hex[:8]}"
    engine = admin_engine()
    with engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}" TEMPLATE "{template_database}"'))
    database = create_engine(database_url(name), pool_size=20, max_overflow=0)
    try:
        yield sessionmaker(bind=database, autoflush=False)
    finally:
        database.dispose()
        with engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        engine.dispose()


def request(index: int = 0) -> OrganizationBootstrapRequest:
    return OrganizationBootstrapRequest(
        organization_name=f"Race Bank {index}",
        admin_full_name=f"Race Admin {index}",
        admin_email=f"race-admin-{index}@example.com",
        admin_password="RaceAdminPassword123!",
    )


def run_concurrently(tasks: list[Callable[[], str]]) -> list[str]:
    barrier = threading.Barrier(len(tasks))
    outcomes: list[str] = []
    lock = threading.Lock()

    def runner(task: Callable[[], str]) -> None:
        barrier.wait()
        try:
            outcome = task()
        except Exception as exc:  # recorded and asserted on by the caller
            outcome = type(exc).__name__
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=runner, args=(task,)) for task in tasks]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return outcomes


def scalar(pg: sessionmaker[Session], statement: Any) -> Any:
    with pg() as db:
        return db.scalar(statement)


def active_organizations(pg: sessionmaker[Session]) -> list[Organization]:
    with pg() as db:
        return list(db.scalars(select(Organization).where(Organization.deleted_at.is_(None))).all())


def bootstrap_task(pg: sessionmaker[Session], index: int) -> Callable[[], str]:
    def task() -> str:
        with pg() as db:
            organization_service.bootstrap_organization(db, request(index), ConsoleEmailBackend())
        return "ok"

    return task


# --- Fresh install through the real migration chain ---------------------------------------------


def test_migrated_fresh_database_contains_one_pristine_placeholder(
    pg: sessionmaker[Session],
) -> None:
    with pg() as db:
        orgs = list(db.scalars(select(Organization)).all())
        assert [(org.slug, org.deleted_at) for org in orgs] == [
            (PLACEHOLDER_ORGANIZATION_SLUG, None)
        ]
        assert organization_service.is_unused_placeholder(db, orgs[0])
        assert organization_service.bootstrap_blocked(db) is False


def test_database_foreign_keys_match_the_reference_scan(pg: sessionmaker[Session]) -> None:
    with pg() as db:
        database_refs = {
            f"{table}.{column}"
            for table, column in db.execute(
                text(
                    "SELECT c.conrelid::regclass::text, a.attname FROM pg_constraint c "
                    "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey) "
                    "WHERE c.contype = 'f' AND c.confrelid = 'organizations'::regclass"
                )
            ).all()
        }
    metadata_refs = {
        f"{table.name}.{column.name}"
        for table in Base.metadata.sorted_tables
        for column in table.columns
        if any(fk.column.table.name == "organizations" for fk in column.foreign_keys)
    }
    assert database_refs == metadata_refs


def test_http_bootstrap_succeeds_on_fresh_install_after_anonymous_traffic(
    pg: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.rate_limit import reset_rate_limit_backend
    from app.main import create_app

    # Same isolation as conftest's client fixture: in-memory rate limiting, never a local Redis.
    monkeypatch.setenv("REDIS_URL", "")
    get_settings.cache_clear()
    reset_rate_limit_backend()

    def override_get_db() -> Iterator[Session]:
        with pg() as db:
            yield db

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_email_backend] = lambda: ConsoleEmailBackend()
    with TestClient(app) as client:
        # Typical pre-bootstrap noise must not "use" the placeholder.
        client.post(
            "/api/v1/auth/login", json={"email": "x@example.com", "password": "nope-nope-1"}
        )
        client.post("/api/v1/auth/forgot-password", json={"email": "x@example.com"})
        client.post("/api/v1/organizations/bootstrap", json={"organization_name": ""})
        response = client.post(
            "/api/v1/organizations/bootstrap",
            json={
                "organization_name": "Fresh Bank",
                "admin_full_name": "Fresh Admin",
                "admin_email": "fresh-admin@example.com",
                "admin_password": "FreshAdminPassword123!",
            },
        )
        second = client.post(
            "/api/v1/organizations/bootstrap",
            json={
                "organization_name": "Late Bank",
                "admin_full_name": "Late Admin",
                "admin_email": "late-admin@example.com",
                "admin_password": "LateAdminPassword123!",
            },
        )

    assert response.status_code == 201, response.text
    assert second.status_code == 409
    assert [org.name for org in active_organizations(pg)] == ["Fresh Bank"]
    retired = scalar(
        pg, select(Organization).where(Organization.slug == PLACEHOLDER_ORGANIZATION_SLUG)
    )
    assert retired is not None and retired.deleted_at is not None


def test_placeholder_with_legacy_membership_blocks_bootstrap(pg: sessionmaker[Session]) -> None:
    with pg() as db:
        placeholder = db.scalar(select(Organization))
        assert placeholder is not None
        user = User(email="legacy@example.com", full_name="Legacy", password_hash="x", role="admin")
        db.add(user)
        db.flush()
        db.add(
            OrganizationMembership(organization_id=placeholder.id, user_id=user.id, role="admin")
        )
        db.commit()

    with pg() as db:
        with pytest.raises(organization_service.OrganizationAlreadyBootstrappedError):
            organization_service.bootstrap_organization(db, request(), ConsoleEmailBackend())
    assert [org.slug for org in active_organizations(pg)] == [PLACEHOLDER_ORGANIZATION_SLUG]


# --- Concurrency --------------------------------------------------------------------------------


def test_concurrent_bootstraps_create_exactly_one_organization(pg: sessionmaker[Session]) -> None:
    outcomes = run_concurrently([bootstrap_task(pg, index) for index in range(8)])

    assert sorted(outcomes) == ["OrganizationAlreadyBootstrappedError"] * 7 + ["ok"]
    active = active_organizations(pg)
    assert len(active) == 1 and active[0].name.startswith("Race Bank ")
    assert scalar(pg, select(func.count()).select_from(OrganizationMembership)) == 1
    assert (
        scalar(pg, select(func.count()).select_from(User).where(User.email.like("race-admin-%")))
        == 1
    )
    assert scalar(pg, select(func.count()).select_from(EmailVerificationToken)) == 1
    assert scalar(pg, select(func.count()).select_from(EmailOutbox)) == 1
    placeholders = scalar(
        pg,
        select(func.count())
        .select_from(Organization)
        .where(
            Organization.slug == PLACEHOLDER_ORGANIZATION_SLUG, Organization.deleted_at.is_not(None)
        ),
    )
    assert placeholders == 1
    assert scalar(pg, text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'")) == 0


def test_bootstrap_racing_legacy_registration_never_orphans_members(
    pg: sessionmaker[Session],
) -> None:
    def register(index: int) -> Callable[[], str]:
        def task() -> str:
            with pg() as db:
                user_service.register_user(
                    db,
                    UserRegister(
                        email=f"legacy-{index}@example.com",
                        full_name="Legacy",
                        password="LegacyPassword123!",
                    ),
                )
            return "registered"

        return task

    outcomes = run_concurrently([bootstrap_task(pg, 0), *(register(i) for i in range(4))])

    assert outcomes.count("registered") == 4, outcomes
    orphaned = scalar(
        pg,
        select(func.count())
        .select_from(OrganizationMembership)
        .join(Organization, Organization.id == OrganizationMembership.organization_id)
        .where(Organization.deleted_at.is_not(None)),
    )
    assert orphaned == 0
    assert len(active_organizations(pg)) == 1
    if "ok" in outcomes:
        assert active_organizations(pg)[0].name == "Race Bank 0"
    else:
        assert outcomes.count("OrganizationAlreadyBootstrappedError") == 1
        assert active_organizations(pg)[0].slug == PLACEHOLDER_ORGANIZATION_SLUG


def test_bootstrap_racing_runtime_placeholder_creation_leaves_one_tenant(
    pg: sessionmaker[Session],
) -> None:
    with pg() as db:  # disposable database: reach the zero-organization state
        db.execute(text("DELETE FROM organizations"))
        db.commit()

    def resolve() -> str:
        with pg() as db:
            get_current_organization_id(db)
            db.commit()
        return "resolved"

    outcomes = run_concurrently([bootstrap_task(pg, 0), *(resolve for _ in range(4))])

    assert "ok" in outcomes, outcomes
    assert outcomes.count("resolved") == 4, outcomes
    active = active_organizations(pg)
    assert [org.name for org in active] == ["Race Bank 0"]
    assert scalar(pg, select(func.count()).select_from(Organization)) <= 2


# --- Failure atomicity ---------------------------------------------------------------------------


def test_failed_bootstrap_rolls_back_everything_and_releases_the_lock(
    pg: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = identity_service.queue_email_verification

    def queue_then_fail(db: Session, user: User) -> EmailVerificationToken:
        original(db, user)
        raise RuntimeError("simulated failure after queuing")

    monkeypatch.setattr(identity_service, "queue_email_verification", queue_then_fail)
    with pg() as db:
        with pytest.raises(RuntimeError):
            organization_service.bootstrap_organization(db, request(), ConsoleEmailBackend())
        assert db.scalar(text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'")) == 0

    assert [org.slug for org in active_organizations(pg)] == [PLACEHOLDER_ORGANIZATION_SLUG]
    assert scalar(pg, select(func.count()).select_from(EmailVerificationToken)) == 0
    assert scalar(pg, select(func.count()).select_from(EmailOutbox)) == 0
    assert scalar(pg, select(func.count()).select_from(User)) == 0

    monkeypatch.setattr(identity_service, "queue_email_verification", original)
    with pg() as db:
        db.execute(text("SET lock_timeout = '2s'"))
        organization_service.bootstrap_organization(db, request(), ConsoleEmailBackend())
    assert [org.name for org in active_organizations(pg)] == ["Race Bank 0"]
