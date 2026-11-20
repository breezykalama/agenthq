from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.core.tenancy import PLACEHOLDER_ORGANIZATION_NAME, PLACEHOLDER_ORGANIZATION_SLUG
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.models.organization import Organization, OrganizationMembership
from app.models.user import User, UserRole
from app.services.email import reset_email_backend


@pytest.fixture(autouse=True)
def isolate_identity_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    # Tests deliver outbox email explicitly (tests/email_helpers.py); never start the
    # background worker against a real database, and skip anti-enumeration padding.
    monkeypatch.setenv("EMAIL_OUTBOX_WORKER_ENABLED", "false")
    monkeypatch.setenv("IDENTITY_MIN_RESPONSE_MS", "0")
    get_settings.cache_clear()


@pytest.fixture()
def public_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Legacy registration is disabled unless explicitly enabled; tests that register enable it."""
    monkeypatch.setenv("ALLOW_PUBLIC_REGISTRATION", "true")
    get_settings.cache_clear()


def _test_client(monkeypatch: pytest.MonkeyPatch, *, admin_is_member: bool) -> Iterator[TestClient]:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://agenthq:agenthq@localhost:5432/agenthq",
    )
    monkeypatch.setenv("REDIS_URL", "")
    get_settings.cache_clear()
    reset_email_backend()

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    Base.metadata.create_all(bind=engine)
    with testing_session_local() as db:
        admin = User(
            email="admin@agenthq.local",
            full_name="Test Admin",
            password_hash=hash_password("AdminPassword123!"),
            role=UserRole.ADMIN,
        )
        db.add(admin)
        if admin_is_member:
            # Organization access is never implicit: the test admin is an explicit member
            # (admin) of the single-tenant organization, as a bootstrapped administrator is.
            organization = Organization(
                name=PLACEHOLDER_ORGANIZATION_NAME, slug=PLACEHOLDER_ORGANIZATION_SLUG
            )
            db.add(organization)
            db.flush()
            db.add(
                OrganizationMembership(
                    organization_id=organization.id, user_id=admin.id, role=UserRole.ADMIN
                )
            )
        db.commit()
        db.refresh(admin)
        admin_token = create_access_token(admin)

    def override_get_db() -> Iterator[Session]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        test_client.headers["Authorization"] = f"Bearer {admin_token}"
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    get_settings.cache_clear()
    reset_email_backend()


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """An admin who is an explicit admin member of the single-tenant organization."""
    yield from _test_client(monkeypatch, admin_is_member=True)


@pytest.fixture()
def member_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Same as ``client``; for modules whose ``client`` is overridden to a fresh install."""
    yield from _test_client(monkeypatch, admin_is_member=True)


@pytest.fixture()
def fresh_install_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A fresh install: no organization exists yet and the seeded account has no membership.
    For bootstrap and identity tests that create the first organization themselves."""
    yield from _test_client(monkeypatch, admin_is_member=False)


@pytest.fixture()
def unauthenticated_client(client: TestClient) -> Iterator[TestClient]:
    with TestClient(client.app) as test_client:
        yield test_client
