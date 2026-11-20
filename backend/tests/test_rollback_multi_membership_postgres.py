"""PostgreSQL-only: multi-membership rollback compatibility (v0.8.2 / rollback/v0.8.2-compat).

The state a rollback must survive is built through the real application: organization bootstrap,
invitations accepted over HTTP (the multi-organization flag is enabled only while building it),
a real password reset and real gateway tokens. The flag is then disabled, as it is in every
deployment, and each test asserts one property the rollback runbook
(docs/ROLLBACK_V0.8.2.md) depends on.

Opt-in, exactly like test_bootstrap_postgres.py: set AGENTHQ_TEST_POSTGRES_URL to a *disposable*
server's maintenance database. Databases named agenthq_rollback_* are created and dropped here.
"""

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from email_helpers import (
    capture_email,
    deliver_outbox,
    raw_token_from_message,
    verify_pending_admin,
)
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.core.config import get_settings
from app.core.rate_limit import reset_rate_limit_backend
from app.core.security import hash_password
from app.db.session import get_db
from app.main import create_app
from app.models.organization import Organization, OrganizationMembership
from app.models.user import User, UserRole

ADMIN_URL = os.environ.get("AGENTHQ_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL, reason="set AGENTHQ_TEST_POSTGRES_URL to a disposable PostgreSQL server"
)
BACKEND = Path(__file__).parents[1]
HEADER = "X-AgentHQ-Organization"
PASSWORD = "RollbackPassword123!"
DENIED = {"detail": "Organization access denied."}
SELECTION_REQUIRED = {"detail": "Organization selection required."}
INVALID_HEADER = {"detail": "Invalid organization header."}
NOT_SUPPORTED = {"detail": "Multiple organizations are not yet supported."}
INVALID_INVITE = {"detail": "Invite is invalid or expired."}


@dataclass(frozen=True)
class World:
    client: TestClient
    session: sessionmaker[Session]
    alembic: Config
    org: dict[str, str]  # a, b (active), c (dual's membership deactivated), d (deleted)
    token: dict[str, str]  # session JWTs; "revoked" predates a password reset
    gateway: dict[str, str]  # gateway tokens per organization
    server: dict[str, str]  # MCP servers per organization
    agent: dict[str, str]
    accepted_invites: dict[str, str]  # raw tokens of accepted invitations
    pending_second_invite: str  # would give a single-membership user a second organization
    reset_password: str


def database_url(name: str) -> str:
    assert ADMIN_URL is not None
    return make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)


def auth(token: str, organization: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if organization is not None:
        headers[HEADER] = organization
    return headers


def set_flag(mp: pytest.MonkeyPatch, enabled: bool) -> None:
    mp.setenv("MULTI_ORGANIZATION_MEMBERSHIPS_ENABLED", "true" if enabled else "false")
    get_settings.cache_clear()


def login(client: TestClient, email: str, password: str = PASSWORD) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return cast(str, response.json()["access_token"])


def invite(
    client: TestClient,
    admin_token: str,
    email: str,
    role: str,
    org: str | None = None,
    full_name: str | None = None,
) -> str:
    body: dict[str, Any] = {"email": email, "role": role}
    if full_name:
        body["full_name"] = full_name
    response = client.post(
        "/api/v1/organization-invites", headers=auth(admin_token, org), json=body
    )
    assert response.status_code == 201, response.text
    return cast(str, response.json()["token"])  # exposed outside production only


def accept(client: TestClient, raw: str, password: str = PASSWORD) -> Any:
    return client.post(
        "/api/v1/organization-invites/accept", json={"token": raw, "password": password}
    )


def membership_state(session: sessionmaker[Session]) -> list[tuple[str, str, str, bool, bool]]:
    with session() as db:
        rows = db.execute(
            select(
                User.email,
                Organization.slug,
                OrganizationMembership.role,
                OrganizationMembership.is_active,
                Organization.deleted_at.is_not(None),
            )
            .join(User, User.id == OrganizationMembership.user_id)
            .join(Organization, Organization.id == OrganizationMembership.organization_id)
            .order_by(User.email, Organization.slug)
        ).all()
    return [
        (email, slug, role.value, active, deleted) for email, slug, role, active, deleted in rows
    ]


def table_fingerprint(session: sessionmaker[Session], table: str) -> str:
    """Deterministic hash of every row of a table (fixed table names from this module only)."""
    statement = (
        f"SELECT md5(coalesce(string_agg(t::text, chr(10) ORDER BY t::text), '')) FROM {table} t"
    )
    with session() as db:
        return cast(str, db.scalar(text(statement)))


@pytest.fixture(scope="module")
def world() -> Iterator[World]:
    name = f"agenthq_rollback_{uuid4().hex[:8]}"
    admin_engine = create_engine(cast(str, ADMIN_URL), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    mp = pytest.MonkeyPatch()
    engine: Engine | None = None
    # Everything after CREATE DATABASE is inside try, so a failed setup still restores the
    # environment (flag included) and drops the database.
    try:
        mp.setenv("DATABASE_URL", database_url(name))
        mp.setenv("REDIS_URL", "")  # in-memory rate limiting, never a local Redis
        mp.setenv("EMAIL_OUTBOX_WORKER_ENABLED", "false")
        mp.setenv("IDENTITY_MIN_RESPONSE_MS", "0")
        mp.setenv("MCP_DISCOVERY_MODE", "mock")
        # One test client (one IP) makes every login and acceptance in this module.
        mp.setenv("AUTH_RATE_LIMIT_ATTEMPTS", "1000")
        set_flag(mp, enabled=True)  # only while building the multi-membership state below
        reset_rate_limit_backend()
        config = Config()  # no ini: keeps fileConfig from disabling loggers (see bootstrap tests)
        config.set_main_option("script_location", str(BACKEND / "alembic"))
        command.upgrade(config, "head")
        engine = create_engine(database_url(name))
        session = sessionmaker(bind=engine, autoflush=False)

        def override_get_db() -> Iterator[Session]:
            with session() as db:
                yield db

        app = create_app()
        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as client:
            mail = capture_email(client)
            # Organization A through the real bootstrap; its administrator is the dual-role user.
            response = client.post(
                "/api/v1/organizations/bootstrap",
                json={
                    "organization_name": "Org A",
                    "admin_full_name": "Dual",
                    "admin_email": "dual@example.com",
                    "admin_password": PASSWORD,
                },
            )
            assert response.status_code == 201, response.text
            org = {"a": response.json()["user"]["organization_membership"]["organization_id"]}
            verify_pending_admin(client)
            # Bootstrap is refused once an organization exists, so B, C and D (and one admin
            # each) are provisioned through the models, as an operator would.
            with session() as db:
                for key in ("b", "c", "d"):
                    organization = Organization(name=f"Org {key.upper()}", slug=f"org-{key}")
                    admin = User(
                        email=f"admin-{key}@example.com",
                        full_name=f"Admin {key}",
                        password_hash=hash_password(PASSWORD),
                        role=UserRole.ADMIN,
                        email_verified=True,
                        email_verified_at=datetime.now(UTC),
                    )
                    db.add_all([organization, admin])
                    db.flush()
                    db.add(
                        OrganizationMembership(
                            organization_id=organization.id, user_id=admin.id, role=UserRole.ADMIN
                        )
                    )
                    org[key] = str(organization.id)
                db.commit()
            token = {key: login(client, f"admin-{key}@example.com") for key in ("b", "c", "d")}
            token["dual"] = login(client, "dual@example.com")

            # Further memberships for the dual user through the normal invitation workflow.
            accepted: dict[str, str] = {}
            for key, role in (("b", "auditor"), ("c", "admin"), ("d", "admin")):
                raw = invite(client, token[key], "dual@example.com", role)
                assert accept(client, raw).status_code == 200
                accepted[f"dual_{key}"] = raw
            # Single-membership accounts (new users created by accepting an invitation).
            for key, admin_key, target_org, role in (
                ("single-a", "dual", org["a"], "operator"),
                ("single-b", "b", None, "agent_owner"),
                ("reset", "b", None, "operator"),
            ):
                raw = invite(client, token[admin_key], f"{key}@example.com", role, target_org, key)
                assert accept(client, raw).status_code == 200
                accepted[key] = raw
                token[key] = login(client, f"{key}@example.com")
            pending_second = invite(client, token["b"], "single-a@example.com", "auditor")

            # Organization C's admin deactivates the dual user's membership there; D is deleted.
            with session() as db:
                dual_id = db.scalar(select(User.id).where(User.email == "dual@example.com"))
            response = client.post(f"/api/v1/users/{dual_id}/deactivate", headers=auth(token["c"]))
            assert response.status_code == 200, response.text
            with session() as db:
                deleted = db.get(Organization, UUID(org["d"]))
                assert deleted is not None
                deleted.deleted_at = datetime.now(UTC)
                db.commit()

            # Tenant resources: an agent and a gateway-enabled MCP server per organization.
            agent: dict[str, str] = {}
            server: dict[str, str] = {}
            gateway: dict[str, str] = {}
            for key, admin_token, target_org in (
                ("a", token["dual"], org["a"]),
                ("b", token["b"], None),
            ):
                headers = auth(admin_token, target_org)
                response = client.post(
                    "/api/v1/agents",
                    headers=headers,
                    json={
                        "name": f"Agent {key.upper()}",
                        "owner": "owner@example.com",
                        "department": "governance",
                        "risk_level": "low",
                    },
                )
                assert response.status_code == 201, response.text
                agent[key] = response.json()["id"]
                response = client.post(
                    "/api/v1/mcp-servers",
                    headers=headers,
                    json={
                        "name": f"Gateway {key.upper()}",
                        "server_url": f"https://{key}.example.com/mcp",
                    },
                )
                assert response.status_code == 201, response.text
                server[key] = response.json()["id"]
                assert (
                    client.post(
                        f"/api/v1/mcp-servers/{server[key]}/sync", headers=headers
                    ).status_code
                    == 200
                )
                response = client.post(
                    "/api/v1/mcp-gateway-tokens",
                    headers=headers,
                    json={"mcp_server_id": server[key], "name": f"Org {key} token"},
                )
                assert response.status_code == 201, response.text
                gateway[key] = response.json()["token"]

            # A session token issued before a password reset must stay revoked.
            token["revoked"] = token["reset"]
            client.post("/api/v1/auth/forgot-password", json={"email": "reset@example.com"})
            deliver_outbox(client, mail)
            links = [m for m in mail.messages if "reset-password" in m.text_body]
            new_password = "ResetPassword456!"
            response = client.post(
                "/api/v1/auth/reset-password",
                json={
                    "token": raw_token_from_message(links[-1].text_body),
                    "new_password": new_password,
                },
            )
            assert response.status_code == 200, response.text

            # Every deployment runs with the flag disabled; so does everything that follows.
            set_flag(mp, enabled=False)
            yield World(
                client=client,
                session=session,
                alembic=config,
                org=org,
                token=token,
                gateway=gateway,
                server=server,
                agent=agent,
                accepted_invites=accepted,
                pending_second_invite=pending_second,
                reset_password=new_password,
            )
    finally:
        mp.undo()
        get_settings.cache_clear()
        reset_rate_limit_backend()
        if engine is not None:
            engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin_engine.dispose()


@pytest.fixture(autouse=True)
def flag_disabled(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    # conftest's autouse fixture clears the settings cache per test; keep the flag explicit.
    set_flag(monkeypatch, enabled=False)
    assert get_settings().multi_organization_memberships_enabled is False


def test_rollback_startup_on_the_release_database_is_a_no_op(world: World) -> None:
    head = ScriptDirectory.from_config(world.alembic).get_current_head()
    tables = ("alembic_version", "organization_memberships", "organizations", "users")
    before = {table: table_fingerprint(world.session, table) for table in tables}
    command.upgrade(world.alembic, "head")  # what every build's start command runs first
    with world.session() as db:
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == head
    assert {table: table_fingerprint(world.session, table) for table in tables} == before


def test_workflow_created_two_active_memberships_with_different_roles(world: World) -> None:
    state = membership_state(world.session)
    dual = [row for row in state if row[0] == "dual@example.com"]
    assert dual == [
        ("dual@example.com", "org-a", "admin", True, False),
        ("dual@example.com", "org-b", "auditor", True, False),
        ("dual@example.com", "org-c", "admin", False, False),
        ("dual@example.com", "org-d", "admin", True, True),
    ]
    me = world.client.get("/api/v1/auth/me", headers=auth(world.token["dual"])).json()
    assert sorted(
        (m["organization_id"], m["role"]) for m in me["organization_memberships"]
    ) == sorted([(world.org["a"], "admin"), (world.org["b"], "auditor")])


def test_missing_selection_is_409_for_a_multi_membership_user(world: World) -> None:
    response = world.client.get("/api/v1/agents", headers=auth(world.token["dual"]))
    assert response.status_code == 409
    assert response.json() == SELECTION_REQUIRED
    me = world.client.get("/api/v1/auth/me", headers=auth(world.token["dual"])).json()
    assert me["selected_organization_id"] is None
    assert me["organization_membership"] is None


def test_header_selects_each_organization_with_its_own_role(world: World) -> None:
    client, dual, org = world.client, world.token["dual"], world.org
    me_a = client.get("/api/v1/auth/me", headers=auth(dual, org["a"])).json()
    assert me_a["selected_organization_id"] == org["a"]
    assert me_a["organization_membership"]["role"] == "admin"
    agents = client.get("/api/v1/agents", headers=auth(dual, org["a"]))
    assert agents.status_code == 200
    assert {a["id"] for a in agents.json()["items"]} >= {world.agent["a"]}
    assert world.agent["b"] not in {a["id"] for a in agents.json()["items"]}
    assert (
        client.get("/api/v1/organization-invites", headers=auth(dual, org["a"])).status_code == 200
    )

    me_b = client.get("/api/v1/auth/me", headers=auth(dual, org["b"])).json()
    assert me_b["selected_organization_id"] == org["b"]
    assert me_b["organization_membership"]["role"] == "auditor"
    assert client.get("/api/v1/audit-logs", headers=auth(dual, org["b"])).status_code == 200
    # Admin powers in A never carry over to B.
    assert (
        client.get("/api/v1/organization-invites", headers=auth(dual, org["b"])).status_code == 403
    )
    assert client.get("/api/v1/agents", headers=auth(dual, org["b"])).status_code == 403
    created = client.post(
        "/api/v1/agents",
        headers=auth(dual, org["b"]),
        json={"name": "not allowed", "owner": "x", "department": "x", "risk_level": "low"},
    )
    assert created.status_code == 403


def test_single_membership_users_need_no_header(world: World) -> None:
    client = world.client
    me = client.get("/api/v1/auth/me", headers=auth(world.token["single-a"])).json()
    assert me["organization_membership"]["organization_id"] == world.org["a"]
    assert me["organization_membership"]["role"] == "operator"
    assert (
        client.get("/api/v1/dashboard/summary", headers=auth(world.token["single-a"])).status_code
        == 200
    )
    owner = client.get("/api/v1/agents", headers=auth(world.token["single-b"]))
    assert owner.status_code == 200


def test_unauthorized_and_malformed_selections_fail_safely(world: World) -> None:
    client, dual, org = world.client, world.token["dual"], world.org
    foreign = client.get(
        "/api/v1/dashboard/summary", headers=auth(world.token["single-a"], org["b"])
    )
    unknown = client.get("/api/v1/agents", headers=auth(dual, str(uuid4())))
    assert foreign.status_code == unknown.status_code == 403
    assert foreign.json() == unknown.json() == DENIED
    duplicate = client.get(
        "/api/v1/agents",
        headers=[("Authorization", f"Bearer {dual}"), (HEADER, org["a"]), (HEADER, org["a"])],
    )
    for response in (
        client.get("/api/v1/agents", headers=auth(dual, "not-a-uuid")),
        client.get("/api/v1/agents", headers=auth(dual, f"{org['a']},{org['b']}")),
        duplicate,
    ):
        assert response.status_code == 400
        assert response.json() == INVALID_HEADER


def test_deactivated_membership_and_deleted_organization_cannot_be_selected(world: World) -> None:
    for key in ("c", "d"):
        response = world.client.get(
            "/api/v1/agents", headers=auth(world.token["dual"], world.org[key])
        )
        assert response.status_code == 403
        assert response.json() == DENIED  # indistinguishable from a foreign organization


def test_cross_tenant_resources_are_isolated(world: World) -> None:
    client, dual, org, agent = world.client, world.token["dual"], world.org, world.agent
    assert (
        client.get(f"/api/v1/agents/{agent['b']}", headers=auth(dual, org["a"])).status_code == 404
    )
    assert (
        client.get(
            f"/api/v1/agents/{agent['a']}", headers=auth(world.token["single-b"])
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/agents/{agent['b']}",
            headers=auth(dual, org["a"]),
            json={"name": "taken over"},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/agents/{agent['a']}", headers=auth(world.token["single-b"])
        ).status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/agents/{agent['a']}", headers=auth(dual, org["a"])).json()["name"]
        == "Agent A"
    )
    # Audit logs stay per organization. Probe events record the ID the prober supplied, in the
    # prober's own organization, exactly as they do for an ID that exists nowhere.
    probe = str(uuid4())
    client.get(f"/api/v1/agents/{probe}", headers=auth(world.token["single-b"]))
    denial = "security.cross_org_access_denied"
    items_b = client.get("/api/v1/audit-logs?limit=100", headers=auth(dual, org["b"])).json()[
        "items"
    ]
    items_a = client.get("/api/v1/audit-logs?limit=100", headers=auth(dual, org["a"])).json()[
        "items"
    ]
    assert {i["entity_id"] for i in items_b if i["action"] == denial} >= {probe, agent["a"]}
    other_b = str([i for i in items_b if i["action"] != denial])
    other_a = str([i for i in items_a if i["action"] != denial])
    assert agent["a"] not in other_b and world.server["a"] not in other_b
    assert agent["b"] not in other_a and world.server["b"] not in other_a


def test_gateway_tokens_stay_in_their_issuing_organization(world: World) -> None:
    client, server = world.client, world.server
    for own, other in (("a", "b"), ("b", "a")):
        gateway = {"Authorization": f"Bearer {world.gateway[own]}"}
        assert (
            client.get(f"/api/v1/mcp-gateway/{server[own]}/tools", headers=gateway).status_code
            == 200
        )
        assert (
            client.get(f"/api/v1/mcp-gateway/{server[other]}/tools", headers=gateway).status_code
            == 401
        )
        # The user organization header never widens a gateway token.
        widened = {**gateway, HEADER: world.org[other]}
        assert (
            client.get(f"/api/v1/mcp-gateway/{server[other]}/tools", headers=widened).status_code
            == 401
        )


def test_password_reset_revoked_jwt_stays_rejected(world: World) -> None:
    client, revoked = world.client, world.token["revoked"]
    assert client.get("/api/v1/auth/me", headers=auth(revoked)).status_code == 401
    assert (
        client.get("/api/v1/dashboard/summary", headers=auth(revoked, world.org["b"])).status_code
        == 401
    )
    fresh = login(client, "reset@example.com", world.reset_password)
    assert client.get("/api/v1/auth/me", headers=auth(fresh)).status_code == 200


def test_accepted_invitations_stay_single_use(world: World) -> None:
    before = membership_state(world.session)
    replies = [accept(world.client, raw) for raw in world.accepted_invites.values()]
    replies.append(accept(world.client, world.accepted_invites["dual_b"], "WrongPassword123!"))
    assert all(r.status_code == 400 and r.json() == INVALID_INVITE for r in replies)
    assert len({r.content for r in replies}) == 1  # nothing reveals whether the password matched
    assert membership_state(world.session) == before


def test_flag_disabled_refuses_new_second_membership_and_keeps_the_invite(world: World) -> None:
    before = membership_state(world.session)
    response = accept(world.client, world.pending_second_invite)
    assert response.status_code == 409
    assert response.json() == NOT_SUPPORTED
    assert membership_state(world.session) == before
    with world.session() as db:
        status = db.scalar(
            text(
                "SELECT status FROM organization_invites WHERE email = "
                "'single-a@example.com' AND role = 'auditor'"
            )
        )
    assert str(status).lower() == "pending"


def test_flag_disabled_keeps_existing_memberships_working_and_intact(world: World) -> None:
    before = table_fingerprint(world.session, "organization_memberships")
    client, dual, org = world.client, world.token["dual"], world.org
    for key, role in (("a", "admin"), ("b", "auditor")):
        me = client.get("/api/v1/auth/me", headers=auth(dual, org[key])).json()
        assert me["organization_membership"]["role"] == role
    accept(client, world.pending_second_invite)  # refused; must not touch memberships
    assert table_fingerprint(world.session, "organization_memberships") == before
