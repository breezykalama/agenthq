"""Legacy registration (POST /api/v1/auth/register) is off unless explicitly enabled.

* Disabled by default in every environment; only ALLOW_PUBLIC_REGISTRATION=true enables it.
* When disabled it answers with the same generic 403 for any email, before any account lookup
  or write.
* Every registration receives the compatibility global role agent_owner (the first account is
  no longer promoted to global admin) and no organization or membership.
* Organization bootstrap never depends on the registration setting.

These tests ignore any developer .env file so the defaults are the repository's own.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.rate_limit import rate_limiter
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.models.audit_log import AuditLog
from app.models.organization import Organization, OrganizationMembership
from app.models.user import User, UserRole

PASSWORD = "StrongPassword123!"
DISABLED = "Public registration is disabled. Ask your organization administrator for an invite."
STRONG_SECRET = "x7Kp2mQ9vR4tY8wZ3nB6cF1hJ5sL0dGaE"


def registration(email: str) -> dict[str, str]:
    return {"email": email, "full_name": "Registrant", "password": PASSWORD}


def ignore_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(Settings.model_config, "env_file", None)


@dataclass(frozen=True)
class Env:
    client: TestClient
    session: sessionmaker[Session]


@contextmanager
def environment(
    monkeypatch: pytest.MonkeyPatch, name: str, allow: str | None, *, seed_admin: bool = False
) -> Iterator[Env]:
    """allow=None leaves ALLOW_PUBLIC_REGISTRATION unset (the default under test)."""
    ignore_env_file(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", name)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://placeholder:x@127.0.0.1:1/unused")
    monkeypatch.setenv("JWT_SECRET_KEY", STRONG_SECRET)
    monkeypatch.setenv("REDIS_URL", "")
    if allow is None:
        monkeypatch.delenv("ALLOW_PUBLIC_REGISTRATION", raising=False)
    else:
        monkeypatch.setenv("ALLOW_PUBLIC_REGISTRATION", allow)
    get_settings.cache_clear()
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(engine)
    if seed_admin:
        with session() as db:
            db.add(
                User(
                    email="existing-admin@example.com",
                    full_name="Existing Admin",
                    password_hash=hash_password(PASSWORD),
                    role=UserRole.ADMIN,
                )
            )
            db.commit()

    def override_get_db() -> Iterator[Session]:
        with session() as db:
            yield db

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    try:
        with (
            patch("app.core.rate_limit.get_rate_limit_backend", return_value=rate_limiter),
            TestClient(app) as client,
        ):
            yield Env(client=client, session=session)
    finally:
        rate_limiter.clear()
        engine.dispose()
        get_settings.cache_clear()


def row_counts(env: Env) -> dict[str, int]:
    with env.session() as db:
        return {
            model.__name__: int(db.scalar(select(func.count()).select_from(model)) or 0)
            for model in (User, Organization, OrganizationMembership, AuditLog)
        }


# --- Settings ---------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["development", "test", "production", "staging"])
def test_setting_defaults_to_disabled_in_every_environment(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    ignore_env_file(monkeypatch)
    monkeypatch.delenv("ALLOW_PUBLIC_REGISTRATION", raising=False)
    settings = Settings(
        DATABASE_URL="postgresql://agenthq:agenthq@localhost:5432/agenthq",
        environment=name,
        JWT_SECRET_KEY=STRONG_SECRET,
    )
    assert settings.public_registration_enabled is False


@pytest.mark.parametrize(
    ("value", "enabled"),
    [("true", True), ("false", False), ("1", True), ("0", False)],
)
def test_only_an_explicit_true_enables_registration(
    monkeypatch: pytest.MonkeyPatch, value: str, enabled: bool
) -> None:
    ignore_env_file(monkeypatch)
    monkeypatch.setenv("ALLOW_PUBLIC_REGISTRATION", value)
    settings = Settings(
        DATABASE_URL="postgresql://agenthq:agenthq@localhost:5432/agenthq",
        environment="development",
    )
    assert settings.public_registration_enabled is enabled


def test_repository_env_template_does_not_enable_registration() -> None:
    template = (Path(__file__).parents[1] / ".env.example").read_text(encoding="utf-8")
    values = [
        line.split("=", 1)[1].strip().lower()
        for line in template.splitlines()
        if line.strip().startswith("ALLOW_PUBLIC_REGISTRATION=")
    ]
    assert values in ([], ["false"])


# --- Disabled endpoint --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["development", "test", "production"])
def test_disabled_by_default_returns_generic_403_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    with environment(monkeypatch, name, None, seed_admin=True) as env:
        before = row_counts(env)
        new = env.client.post("/api/v1/auth/register", json=registration("new@example.com"))
        existing = env.client.post(
            "/api/v1/auth/register", json=registration("existing-admin@example.com")
        )
        assert new.status_code == existing.status_code == 403
        assert new.json() == existing.json() == {"detail": DISABLED}
        assert new.content == existing.content  # nothing reveals that an account exists
        assert row_counts(env) == before  # no user, organization, membership or audit write


def test_disabled_registration_never_looks_up_the_account(monkeypatch: pytest.MonkeyPatch) -> None:
    with (
        environment(monkeypatch, "development", "false") as env,
        patch("app.repositories.users.get_user_by_email") as lookup,
        patch("app.services.users.register_user") as register_user,
    ):
        response = env.client.post("/api/v1/auth/register", json=registration("x@example.com"))
        assert response.status_code == 403
        lookup.assert_not_called()
        register_user.assert_not_called()


# --- Enabled endpoint ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["development", "test", "production"])
def test_explicitly_enabled_registration_assigns_agent_owner_and_no_membership(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    with environment(monkeypatch, name, "true") as env:
        first = env.client.post("/api/v1/auth/register", json=registration("first@example.com"))
        second = env.client.post("/api/v1/auth/register", json=registration("second@example.com"))
        assert first.status_code == second.status_code == 201, (first.text, second.text)
        assert first.json()["role"] == second.json()["role"] == "agent_owner"
        assert first.json()["organization_membership"] is None
        with env.session() as db:
            roles = {u.email: u.role for u in db.scalars(select(User))}
            assert roles == {
                "first@example.com": UserRole.AGENT_OWNER,
                "second@example.com": UserRole.AGENT_OWNER,
            }
            assert int(db.scalar(select(func.count()).select_from(Organization)) or 0) == 0
            assert (
                int(db.scalar(select(func.count()).select_from(OrganizationMembership)) or 0) == 0
            )


def test_registration_never_changes_existing_users(monkeypatch: pytest.MonkeyPatch) -> None:
    with environment(monkeypatch, "development", "true", seed_admin=True) as env:
        with env.session() as db:
            existing = db.scalar(select(User).where(User.email == "existing-admin@example.com"))
            assert existing is not None
            token = create_access_token(existing)
        registered = env.client.post("/api/v1/auth/register", json=registration("n@example.com"))
        assert registered.status_code == 201
        assert registered.json()["role"] == "agent_owner"
        me = env.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200  # an existing token keeps working (JWT contract unchanged)
        assert me.json()["role"] == "admin"  # the existing global role is left as it was


# --- Bootstrap does not depend on the registration setting ------------------------------------


@pytest.mark.parametrize("allow", [None, "false"])
def test_bootstrap_works_while_registration_is_disabled(
    monkeypatch: pytest.MonkeyPatch, allow: str | None
) -> None:
    with environment(monkeypatch, "development", allow) as env:
        assert (
            env.client.post(
                "/api/v1/auth/register", json=registration("blocked@example.com")
            ).status_code
            == 403
        )
        response = env.client.post(
            "/api/v1/organizations/bootstrap",
            json={
                "organization_name": "Founding Org",
                "admin_full_name": "Founder",
                "admin_email": "founder@example.com",
                "admin_password": PASSWORD,
            },
        )
        assert response.status_code == 201, response.text
        user = response.json()["user"]
        assert user["role"] == "admin"
        assert user["organization_membership"]["role"] == "admin"
        assert user["organization_membership"]["organization"]["name"] == "Founding Org"


# --- PostgreSQL (opt-in): a migrated install keeps its unused placeholder after registration --

ADMIN_URL = os.environ.get("AGENTHQ_TEST_POSTGRES_URL")


@pytest.mark.skipif(
    not ADMIN_URL, reason="set AGENTHQ_TEST_POSTGRES_URL to a disposable PostgreSQL server"
)
def test_postgres_registration_leaves_bootstrap_available(monkeypatch: pytest.MonkeyPatch) -> None:
    from alembic.config import Config
    from sqlalchemy.engine import make_url

    from alembic import command
    from app.core.rate_limit import reset_rate_limit_backend

    assert ADMIN_URL is not None
    name = f"agenthq_registration_{uuid4().hex[:8]}"
    url = make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)
    admin_engine = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    engine: Any = None
    try:
        ignore_env_file(monkeypatch)
        monkeypatch.setenv("DATABASE_URL", url)
        monkeypatch.setenv("REDIS_URL", "")
        monkeypatch.setenv("ALLOW_PUBLIC_REGISTRATION", "true")
        get_settings.cache_clear()
        reset_rate_limit_backend()
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
        command.upgrade(config, "head")
        engine = create_engine(url)
        session = sessionmaker(bind=engine, autoflush=False)

        def override_get_db() -> Iterator[Session]:
            with session() as db:
                yield db

        app = create_app()
        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as client:
            first = client.post("/api/v1/auth/register", json=registration("first@example.com"))
            assert first.status_code == 201, first.text
            assert first.json()["role"] == "agent_owner"
            with session() as db:
                memberships = int(
                    db.scalar(select(func.count()).select_from(OrganizationMembership)) or 0
                )
                roles = [u.role for u in db.scalars(select(User))]
            assert memberships == 0 and roles == [UserRole.AGENT_OWNER]
            # The registrant did not "use" the install: bootstrap still creates the first org.
            bootstrap = client.post(
                "/api/v1/organizations/bootstrap",
                json={
                    "organization_name": "Founding Org",
                    "admin_full_name": "Founder",
                    "admin_email": "founder@example.com",
                    "admin_password": PASSWORD,
                },
            )
            assert bootstrap.status_code == 201, bootstrap.text
            assert bootstrap.json()["user"]["organization_membership"]["role"] == "admin"
    finally:
        get_settings.cache_clear()
        reset_rate_limit_backend()
        if engine is not None:
            engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin_engine.dispose()
