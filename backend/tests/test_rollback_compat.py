"""Regression tests for the v0.8.1-compatible rollback build.

This build is v0.8.0 (ca1bd62) plus the minimum needed to run safely against a database that
v0.8.1 has already migrated:

1. Alembic recognises revision 202611170001 (startup no longer fails).
2. Every audit action written by v0.8.1 deserializes (no HTTP 500 on audit pages).
3. users.auth_version is enforced, so sessions revoked by a v0.8.1 password reset stay revoked.
"""

import ast
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

import jwt
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models.audit_log import AuditAction, AuditLog
from app.models.organization import Organization
from app.models.user import User

BACKEND = Path(__file__).parents[1]
VERSIONS = BACKEND / "alembic" / "versions"
V081_MIGRATIONS = (
    "202606270001_add_email_identity_flows.py",
    "202611170001_harden_identity_flows.py",
)
PASSWORD = "RollbackPassword123!"


def database_session(client: TestClient) -> Session:
    app = cast(FastAPI, client.app)
    override = cast(Callable[[], Iterator[Session]], app.dependency_overrides[get_db])
    return next(override())


def migration_audit_actions(name: str) -> set[str]:
    tree = ast.parse((VERSIONS / name).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "AUDIT_ACTIONS" for target in node.targets
        ):
            return {cast(str, element.value) for element in cast(ast.Tuple, node.value).elts}  # type: ignore[attr-defined]
    raise AssertionError(f"{name} defines no AUDIT_ACTIONS")


def encode(claims: dict[str, object]) -> str:
    settings = get_settings()
    payload = {"exp": datetime.now(UTC) + timedelta(minutes=30), **claims}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def register_and_login(client: TestClient, email: str) -> tuple[User, str]:
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": email, "full_name": "Rollback User", "password": PASSWORD},
    )
    assert registered.status_code == 201
    login = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    with database_session(client) as db:
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None
        db.expunge(user)
    return user, cast(str, login.json()["access_token"])


def set_auth_version(client: TestClient, user: User, version: int) -> None:
    """Simulate a v0.8.1 password reset, which increments users.auth_version."""
    with database_session(client) as db:
        stored = db.get(User, user.id)
        assert stored is not None
        stored.auth_version = version
        db.commit()


# --- 1. Migration compatibility ---------------------------------------------------------------


def test_alembic_head_is_the_v081_schema() -> None:
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))

    assert script.get_heads() == ["202611170001"]
    assert script.get_revision("202611170001").down_revision == "202606270001"
    assert script.get_revision("202606270001").down_revision == "202606130005"


def test_v081_migrations_are_shipped_unmodified_and_startup_never_downgrades() -> None:
    for name in V081_MIGRATIONS:
        assert (VERSIONS / name).is_file()
    dockerfile = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
    assert "alembic upgrade head" in dockerfile
    assert "downgrade" not in dockerfile


# --- 2. Audit compatibility -------------------------------------------------------------------


def test_every_v081_audit_action_is_defined() -> None:
    values = {action.value for action in AuditAction}
    for name in V081_MIGRATIONS:
        missing = migration_audit_actions(name) - values
        assert missing == set(), (name, missing)


def test_every_model_audit_action_exists_in_some_migration() -> None:
    sources = "\n".join(path.read_text(encoding="utf-8") for path in VERSIONS.glob("*.py"))
    missing = [
        action.value
        for action in AuditAction
        if f"'{action.value}'" not in sources and f'"{action.value}"' not in sources
    ]
    assert missing == []


def test_audit_api_reads_v081_identity_events_alongside_legacy_events(client: TestClient) -> None:
    assert client.get("/api/v1/audit-logs").status_code == 200  # establishes org membership
    new_actions = set().union(*(migration_audit_actions(name) for name in V081_MIGRATIONS))
    with database_session(client) as db:
        organization = db.scalar(
            select(Organization).where(Organization.slug == "default-organization")
        )
        assert organization is not None
        for action in sorted(new_actions):
            db.add(
                AuditLog(
                    organization_id=organization.id,
                    actor="system",
                    action=AuditAction(action),
                    entity_type="user",
                    entity_id=uuid4(),
                )
            )
        db.add(
            AuditLog(
                organization_id=organization.id,
                actor="system",
                action=AuditAction.AGENT_CREATED,
                entity_type="agent",
                entity_id=uuid4(),
            )
        )
        db.commit()

    listing = client.get("/api/v1/audit-logs", params={"limit": 100})
    filtered = client.get("/api/v1/audit-logs", params={"action": "auth.password_reset_completed"})

    assert listing.status_code == 200
    returned = {item["action"] for item in listing.json()["items"]}
    assert new_actions <= returned
    assert "agent.created" in returned
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1


# --- 3. Session revocation --------------------------------------------------------------------


def test_new_tokens_carry_the_current_auth_version(unauthenticated_client: TestClient) -> None:
    user, token = register_and_login(unauthenticated_client, "claims@example.com")
    claims = jwt.decode(token, options={"verify_signature": False})

    assert claims["av"] == user.auth_version == 0
    assert unauthenticated_client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 200


def test_legacy_token_without_version_claim_works_only_at_version_zero(
    unauthenticated_client: TestClient,
) -> None:
    user, _ = register_and_login(unauthenticated_client, "legacy@example.com")
    legacy = encode({"sub": str(user.id), "role": user.role.value})  # pre-v0.8.1 format

    assert unauthenticated_client.get("/api/v1/auth/me", headers=bearer(legacy)).status_code == 200
    set_auth_version(unauthenticated_client, user, 1)
    assert unauthenticated_client.get("/api/v1/auth/me", headers=bearer(legacy)).status_code == 401


def test_password_reset_revoked_token_stays_rejected(unauthenticated_client: TestClient) -> None:
    user, before_reset = register_and_login(unauthenticated_client, "revoked@example.com")
    set_auth_version(unauthenticated_client, user, 1)

    me = unauthenticated_client.get("/api/v1/auth/me", headers=bearer(before_reset))
    org_route = unauthenticated_client.get("/api/v1/agents", headers=bearer(before_reset))

    assert me.status_code == 401
    assert org_route.status_code == 401


def test_token_matching_current_version_is_accepted(unauthenticated_client: TestClient) -> None:
    user, _ = register_and_login(unauthenticated_client, "current@example.com")
    set_auth_version(unauthenticated_client, user, 3)
    relogin = unauthenticated_client.post(
        "/api/v1/auth/login", json={"email": "current@example.com", "password": PASSWORD}
    )
    issued = relogin.json()["access_token"]
    crafted = encode({"sub": str(user.id), "role": user.role.value, "av": 3})

    assert jwt.decode(issued, options={"verify_signature": False})["av"] == 3
    assert unauthenticated_client.get("/api/v1/auth/me", headers=bearer(issued)).status_code == 200
    assert unauthenticated_client.get("/api/v1/auth/me", headers=bearer(crafted)).status_code == 200


@pytest.mark.parametrize("claim", [2, 0, "3", 3.0, True, None, [3]])
def test_mismatched_or_malformed_version_claims_are_rejected(
    unauthenticated_client: TestClient,
    claim: object,
) -> None:
    user, _ = register_and_login(unauthenticated_client, "malformed@example.com")
    set_auth_version(unauthenticated_client, user, 3)
    token = encode({"sub": str(user.id), "role": user.role.value, "av": claim})

    assert unauthenticated_client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 401


def test_inactive_user_rejected_even_with_matching_version(
    unauthenticated_client: TestClient,
) -> None:
    user, token = register_and_login(unauthenticated_client, "inactive@example.com")
    with database_session(unauthenticated_client) as db:
        stored = db.get(User, user.id)
        assert stored is not None
        stored.is_active = False
        db.commit()

    assert unauthenticated_client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 401
