"""No implicit organization membership.

Organization access comes only from an explicit, active membership: organization bootstrap,
an accepted invitation, or an administrator's change to an existing membership. It never comes
from the global users.role, from the existence of default-organization, from registering, or
from merely calling a protected endpoint. The behavior is the same in every environment.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.rate_limit import rate_limiter
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.models.audit_log import AuditLog
from app.models.organization import Organization, OrganizationMembership
from app.models.user import User, UserRole

ENVIRONMENTS = ("development", "test", "production")
MEMBERSHIP_REQUIRED = {"detail": "Organization membership required."}
PASSWORD = "StrongPassword123!"
ORG_ROUTES = ("/api/v1/agents", "/api/v1/users", "/api/v1/dashboard/summary", "/api/v1/audit-logs")


@dataclass(frozen=True)
class Env:
    client: TestClient
    session: sessionmaker[Session]
    tokens: dict[str, dict[str, str]]


@contextmanager
def environment(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    *,
    organizations: tuple[str, ...] = (),
    public_registration: bool = False,
) -> Iterator[Env]:
    """users without memberships (global admin and agent_owner) plus the given organizations
    (slugs), e.g. the legacy "default-organization" placeholder."""
    monkeypatch.setenv("ENVIRONMENT", name)
    monkeypatch.setenv("JWT_SECRET_KEY", "x7Kp2mQ9vR4tY8wZ3nB6cF1hJ5sL0dGaE")  # production-strength
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("ALLOW_PUBLIC_REGISTRATION", "true" if public_registration else "false")
    get_settings.cache_clear()
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(engine)
    with session() as db:
        db.add_all(Organization(name=slug, slug=slug) for slug in organizations)
        users = {
            "global_admin": User(
                email="global-admin@example.com",
                full_name="Global Admin",
                password_hash=hash_password(PASSWORD),
                role=UserRole.ADMIN,
            ),
            "global_owner": User(
                email="global-owner@example.com",
                full_name="Global Owner",
                password_hash=hash_password(PASSWORD),
                role=UserRole.AGENT_OWNER,
            ),
        }
        db.add_all(users.values())
        db.commit()
        tokens = {
            key: {"Authorization": f"Bearer {create_access_token(user)}"}
            for key, user in users.items()
        }

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
            yield Env(client=client, session=session, tokens=tokens)
    finally:
        rate_limiter.clear()
        engine.dispose()
        get_settings.cache_clear()


def counts(env: Env) -> dict[str, int]:
    with env.session() as db:
        return {
            model.__name__: int(db.scalar(select(func.count()).select_from(model)) or 0)
            for model in (Organization, OrganizationMembership, User)
        }


@pytest.mark.parametrize("name", ENVIRONMENTS)
@pytest.mark.parametrize(
    "organizations", [(), ("default-organization",)], ids=["no-org", "default-org"]
)
@pytest.mark.parametrize("user", ["global_admin", "global_owner"])
def test_user_without_membership_is_denied_and_nothing_is_created(
    monkeypatch: pytest.MonkeyPatch, name: str, organizations: tuple[str, ...], user: str
) -> None:
    with environment(monkeypatch, name, organizations=organizations) as env:
        before = counts(env)
        for route in ORG_ROUTES:
            response = env.client.get(route, headers=env.tokens[user])
            assert response.status_code == 403, (route, response.status_code)
            assert response.json() == MEMBERSHIP_REQUIRED, route
        # A write attempt is refused the same way and creates nothing.
        created = env.client.post(
            "/api/v1/agents",
            headers=env.tokens[user],
            json={"name": "implicit", "owner": "x", "department": "x", "risk_level": "low"},
        )
        assert created.status_code == 403
        assert counts(env) == before


@pytest.mark.parametrize("name", ENVIRONMENTS)
def test_identity_routes_stay_available_without_membership(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    with environment(monkeypatch, name, organizations=("default-organization",)) as env:
        before = counts(env)
        me = env.client.get("/api/v1/auth/me", headers=env.tokens["global_admin"])
        assert me.status_code == 200
        assert me.json()["organization_membership"] is None
        assert me.json()["organization_memberships"] == []
        assert me.json()["selected_organization_id"] is None
        listed = env.client.get("/api/v1/organizations", headers=env.tokens["global_admin"])
        assert listed.status_code == 200
        assert listed.json() == {"items": [], "total": 0}
        assert counts(env) == before


@pytest.mark.parametrize("name", ("development", "test"))
@pytest.mark.parametrize(
    "organizations",
    [(), ("default-organization",), ("real-org",)],
    ids=["no-org", "default-org", "real-org"],
)
def test_registration_never_attaches_an_organization(
    monkeypatch: pytest.MonkeyPatch, name: str, organizations: tuple[str, ...]
) -> None:
    with environment(
        monkeypatch, name, organizations=organizations, public_registration=True
    ) as env:
        with env.session() as db:
            orgs_before = int(db.scalar(select(func.count()).select_from(Organization)) or 0)
            memberships_before = int(
                db.scalar(select(func.count()).select_from(OrganizationMembership)) or 0
            )
        response = env.client.post(
            "/api/v1/auth/register",
            json={"email": "newcomer@example.com", "full_name": "Newcomer", "password": PASSWORD},
        )
        assert response.status_code == 201, response.text
        assert response.json()["organization_membership"] is None
        with env.session() as db:
            assert (
                int(db.scalar(select(func.count()).select_from(Organization)) or 0) == orgs_before
            )
            assert (
                int(db.scalar(select(func.count()).select_from(OrganizationMembership)) or 0)
                == memberships_before
            )
        login = env.client.post(
            "/api/v1/auth/login", json={"email": "newcomer@example.com", "password": PASSWORD}
        )
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        denied = env.client.get("/api/v1/agents", headers=headers)
        assert denied.status_code == 403
        assert denied.json() == MEMBERSHIP_REQUIRED
        with env.session() as db:
            assert (
                int(db.scalar(select(func.count()).select_from(OrganizationMembership)) or 0)
                == memberships_before
            )


@pytest.mark.parametrize("name", ENVIRONMENTS)
def test_global_admin_role_never_upgrades_an_explicit_membership(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    with environment(monkeypatch, name, organizations=("real-org",)) as env:
        with env.session() as db:
            org = db.scalar(select(Organization).where(Organization.slug == "real-org"))
            admin = db.scalar(select(User).where(User.email == "global-admin@example.com"))
            assert org is not None and admin is not None
            db.add(
                OrganizationMembership(
                    organization_id=org.id, user_id=admin.id, role=UserRole.AUDITOR
                )
            )
            db.commit()
        headers = env.tokens["global_admin"]
        assert (
            env.client.get("/api/v1/audit-logs", headers=headers).status_code == 200
        )  # auditor may
        for route in ("/api/v1/agents", "/api/v1/users", "/api/v1/organization-invites"):
            assert env.client.get(route, headers=headers).status_code == 403, route  # admin may not
        me = env.client.get("/api/v1/auth/me", headers=headers).json()
        assert me["organization_membership"]["role"] == "auditor"


def test_denials_record_no_membership_or_organization_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with environment(monkeypatch, "development") as env:  # no organization at all
        for _ in range(3):
            env.client.get("/api/v1/agents", headers=env.tokens["global_admin"])
        with env.session() as db:
            organizations: Any = db.scalars(select(Organization)).all()
            memberships = db.scalars(select(OrganizationMembership)).all()
            audit_actions = [row.action.value for row in db.scalars(select(AuditLog)).all()]
        assert organizations == [] and memberships == []  # no placeholder, no membership
        assert "organization_membership.created" not in audit_actions
