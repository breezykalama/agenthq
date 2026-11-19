"""v0.8.2 phase 1: explicit organization selection with X-AgentHQ-Organization.

The header only ever chooses among the caller's own active memberships in non-deleted
organizations. These tests cover backward compatibility, explicit selection, per-membership
roles, malformed headers, unauthorized selections (and that they leak nothing), cross-tenant
resource access, the gateway ignoring the header, auth ordering, and the multi-membership flag.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.rate_limit import rate_limiter
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.models.agent import Agent, AgentRiskLevel
from app.models.audit_log import AuditLog
from app.models.organization import Organization, OrganizationMembership
from app.models.user import User, UserRole

HEADER = "X-AgentHQ-Organization"
PASSWORD = "StrongPassword123!"
DENIED = {"detail": "Organization access denied."}
SELECTION_REQUIRED = {"detail": "Organization selection required."}
INVALID_HEADER = {"detail": "Invalid organization header."}


@dataclass(frozen=True)
class World:
    client: TestClient
    session_local: sessionmaker[Session]
    org: dict[str, UUID]  # a, b, c (dual's membership inactive), d (deleted)
    user: dict[str, UUID]
    auth: dict[str, dict[str, str]]
    agent_a: UUID
    agent_b: UUID


def bearer(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


@contextmanager
def world() -> Iterator[World]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(engine)
    with session_local() as db:
        orgs = {
            "a": Organization(name="Org A", slug="org-a"),
            "b": Organization(name="Org B", slug="org-b"),
            "c": Organization(name="Org C", slug="org-c"),
            "d": Organization(name="Org D", slug="org-d", deleted_at=datetime.now(UTC)),
        }

        def person(email: str, role: UserRole = UserRole.AGENT_OWNER, **extra: Any) -> User:
            return User(
                email=email,
                full_name=email,
                password_hash=hash_password(PASSWORD),
                role=role,
                **extra,
            )

        users = {
            "admin_a": person("admin-a@example.com"),
            "admin_b": person("admin-b@example.com"),
            "single": person("single@example.com"),
            # Global users.role is admin on purpose: it must never grant anything.
            "dual": person("dual@example.com", UserRole.ADMIN),
            "dual_admin": person("dual-admin@example.com"),
            "none": person("none@example.com", UserRole.ADMIN),
            "unverified": person(
                "unverified@example.com", email_verification_required=True, email_verified=False
            ),
        }
        db.add_all([*orgs.values(), *users.values()])
        db.flush()

        def member(user: str, org: str, role: UserRole, active: bool = True) -> None:
            db.add(
                OrganizationMembership(
                    organization_id=orgs[org].id,
                    user_id=users[user].id,
                    role=role,
                    is_active=active,
                )
            )

        member("admin_a", "a", UserRole.ADMIN)
        member("admin_b", "b", UserRole.ADMIN)
        member("single", "a", UserRole.OPERATOR)
        member("dual", "a", UserRole.ADMIN)
        member("dual", "b", UserRole.AUDITOR)
        member("dual", "c", UserRole.ADMIN, active=False)
        member("dual", "d", UserRole.ADMIN)
        member("dual_admin", "a", UserRole.ADMIN)
        member("dual_admin", "b", UserRole.ADMIN)
        member("unverified", "a", UserRole.ADMIN)
        agents = {
            key: Agent(
                organization_id=orgs[key].id,
                name=f"Agent {key}",
                owner="owner@example.com",
                department="governance",
                risk_level=AgentRiskLevel.LOW,
            )
            for key in ("a", "b")
        }
        db.add_all(agents.values())
        db.commit()
        snapshot = World(
            client=None,  # type: ignore[arg-type]
            session_local=session_local,
            org={key: value.id for key, value in orgs.items()},
            user={key: value.id for key, value in users.items()},
            auth={key: bearer(value) for key, value in users.items()},
            agent_a=agents["a"].id,
            agent_b=agents["b"].id,
        )

    def override_get_db() -> Iterator[Session]:
        with session_local() as db:
            yield db

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    with (
        patch("app.core.rate_limit.get_rate_limit_backend", return_value=rate_limiter),
        TestClient(app) as client,
    ):
        yield World(**{**snapshot.__dict__, "client": client})
    rate_limiter.clear()
    engine.dispose()


def h(w: World, user: str, org: str | UUID | None = None) -> dict[str, str]:
    headers = dict(w.auth[user])
    if org is not None:
        headers[HEADER] = str(w.org[org] if isinstance(org, str) and org in w.org else org)
    return headers


def audit_rows(w: World) -> list[AuditLog]:
    with w.session_local() as db:
        return list(db.scalars(select(AuditLog)).all())


ORG_ROUTES = [
    "/api/v1/agents",
    "/api/v1/users",
    "/api/v1/audit-logs",
    "/api/v1/organization-invites",
    "/api/v1/mcp-servers",
    "/api/v1/policy-rules",
    "/api/v1/dashboard/summary",
]


# --- Backward compatibility ------------------------------------------------------------------


def test_single_membership_works_without_header() -> None:
    with world() as w:
        assert w.client.get("/api/v1/agents", headers=h(w, "admin_a")).status_code == 200
        assert w.client.get("/api/v1/users", headers=h(w, "admin_a")).status_code == 200
        listed = w.client.get("/api/v1/agents", headers=h(w, "admin_a")).json()["items"]
        assert [item["id"] for item in listed] == [str(w.agent_a)]


def test_single_membership_with_own_header_works() -> None:
    with world() as w:
        assert w.client.get("/api/v1/users", headers=h(w, "admin_a", "a")).status_code == 200


def test_routes_without_membership_requirement_still_work_with_any_header() -> None:
    with world() as w:
        for user in ("dual", "none"):
            assert w.client.get("/api/v1/auth/me", headers=h(w, user, "b")).status_code == 200
        assert w.client.get("/health", headers={HEADER: "garbage"}).status_code == 200


# --- Selection rules ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ORG_ROUTES)
def test_multiple_memberships_without_header_require_selection(path: str) -> None:
    with world() as w:
        response = w.client.get(path, headers=h(w, "dual"))
        assert response.status_code == 409
        assert response.json() == SELECTION_REQUIRED


def test_no_membership_keeps_existing_403() -> None:
    with world() as w:
        response = w.client.get("/api/v1/agents", headers=h(w, "none"))
        assert response.status_code == 403
        assert response.json() == {"detail": "Organization membership required."}


def test_roles_come_from_the_selected_membership_not_users_role() -> None:
    with world() as w:
        # Organization A: admin membership.
        assert w.client.get("/api/v1/users", headers=h(w, "dual", "a")).status_code == 200
        assert w.client.get("/api/v1/agents", headers=h(w, "dual", "a")).status_code == 200
        invites_a = w.client.get("/api/v1/organization-invites", headers=h(w, "dual", "a"))
        assert invites_a.status_code == 200
        # Organization B: auditor membership, although users.role is admin.
        assert w.client.get("/api/v1/audit-logs", headers=h(w, "dual", "b")).status_code == 200
        for path in ("/api/v1/users", "/api/v1/agents", "/api/v1/organization-invites"):
            assert w.client.get(path, headers=h(w, "dual", "b")).status_code == 403, path
        created = w.client.post(
            "/api/v1/agents",
            headers=h(w, "dual", "b"),
            json={
                "name": "Escalation",
                "owner": "dual@example.com",
                "department": "x",
                "risk_level": "low",
            },
        )
        assert created.status_code == 403


def test_selected_organization_scopes_resources_and_writes() -> None:
    with world() as w:
        list_a = w.client.get("/api/v1/agents", headers=h(w, "dual_admin", "a")).json()
        list_b = w.client.get("/api/v1/agents", headers=h(w, "dual_admin", "b")).json()
        assert [item["id"] for item in list_a["items"]] == [str(w.agent_a)]
        assert [item["id"] for item in list_b["items"]] == [str(w.agent_b)]

        created = w.client.post(
            "/api/v1/agents",
            headers=h(w, "dual_admin", "b"),
            json={
                "name": "Made in B",
                "owner": "o@example.com",
                "department": "d",
                "risk_level": "low",
            },
        )
        assert created.status_code == 201
        with w.session_local() as db:
            agent = db.get(Agent, UUID(created.json()["id"]))
            assert agent is not None and agent.organization_id == w.org["b"]


def test_cross_tenant_resource_ids_are_hidden_under_each_selection() -> None:
    with world() as w:
        for selected, foreign in (("a", w.agent_b), ("b", w.agent_a)):
            headers = h(w, "dual_admin", selected)
            assert w.client.get(f"/api/v1/agents/{foreign}", headers=headers).status_code == 404
            patched = w.client.patch(
                f"/api/v1/agents/{foreign}", headers=headers, json={"description": "x"}
            )
            assert patched.status_code == 404
        # A user who is only in A cannot reach B's agent even by naming B.
        response = w.client.get(f"/api/v1/agents/{w.agent_b}", headers=h(w, "admin_a", "b"))
        assert response.status_code == 403
        assert response.json() == DENIED


# --- Malformed headers -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "not-a-uuid",
        "12345",
        "{00000000-0000-0000-0000-000000000000}",
        "urn:uuid:00000000-0000-0000-0000-000000000000",
        "00000000000000000000000000000000",
        "00000000-0000-0000-0000-000000000000, 00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-00000000000g",
    ],
)
def test_malformed_headers_are_rejected_without_echo(value: str) -> None:
    with world() as w:
        response = w.client.get("/api/v1/agents", headers=h(w, "admin_a", value))
        assert response.status_code == 400
        assert response.json() == INVALID_HEADER
        if value.strip():
            assert value.strip() not in response.text


def test_duplicate_headers_are_rejected_even_when_identical() -> None:
    with world() as w:
        organization = str(w.org["a"])
        headers = [
            ("Authorization", w.auth["admin_a"]["Authorization"]),
            (HEADER, organization),
            (HEADER, organization),
        ]
        response = w.client.get("/api/v1/agents", headers=headers)
        assert response.status_code == 400
        assert response.json() == INVALID_HEADER


def test_uppercase_canonical_uuid_is_accepted() -> None:
    with world() as w:
        headers = h(w, "admin_a", str(w.org["a"]).upper())
        assert w.client.get("/api/v1/users", headers=headers).status_code == 200


# --- Unauthorized selections leak nothing -----------------------------------------------------


def test_unknown_foreign_deleted_and_inactive_selections_are_indistinguishable() -> None:
    with world() as w:
        responses = {
            "unknown": w.client.get("/api/v1/agents", headers=h(w, "dual", uuid4())),
            "foreign": w.client.get("/api/v1/agents", headers=h(w, "single", "b")),
            "deleted": w.client.get("/api/v1/agents", headers=h(w, "dual", "d")),
            "inactive": w.client.get("/api/v1/agents", headers=h(w, "dual", "c")),
        }
        for name, response in responses.items():
            assert response.status_code == 403, name
            assert response.json() == DENIED, name
            assert response.content == responses["unknown"].content, name
            for key in ("a", "b", "c", "d"):
                assert str(w.org[key]) not in response.text
                assert f"Org {key.upper()}" not in response.text


def test_denied_selection_is_never_audited_into_the_target_organization() -> None:
    with world() as w:
        target = w.org["b"]
        before = {row.id for row in audit_rows(w) if row.organization_id == target}
        unknown = uuid4()

        w.client.get("/api/v1/agents", headers=h(w, "single", "b"))
        w.client.get("/api/v1/agents", headers=h(w, "dual", unknown))
        w.client.get("/api/v1/agents", headers=h(w, "dual", "d"))

        rows = audit_rows(w)
        assert {row.id for row in rows if row.organization_id == target} == before
        denied = [
            row
            for row in rows
            if (row.event_metadata or {}).get("attempted_action") == "select_organization"
        ]
        assert len(denied) == 3
        by_actor = {row.actor_user_id: row.organization_id for row in denied}
        # Single-membership caller: attributed to their own organization. Multi: no organization.
        assert by_actor[w.user["single"]] == w.org["a"]
        assert by_actor[w.user["dual"]] is None
        serialized = json.dumps([row.event_metadata for row in rows] + [row.reason for row in rows])
        for leaked in (str(target), str(unknown), str(w.org["d"])):
            assert leaked not in serialized


# --- Auth ordering -----------------------------------------------------------------------------


def test_revoked_jwt_is_rejected_before_any_selection_logic() -> None:
    with world() as w:
        stale = h(w, "dual", "a")
        with w.session_local() as db:
            user = db.get(User, w.user["dual"])
            assert user is not None
            user.auth_version += 1  # what a completed password reset does
            db.commit()
        for headers in (stale, {**stale, HEADER: "garbage"}, {**stale, HEADER: str(uuid4())}):
            response = w.client.get("/api/v1/agents", headers=headers)
            assert response.status_code == 401


def test_email_verification_gate_precedes_selection() -> None:
    with world() as w:
        for org in ("a", "garbage", uuid4()):
            response = w.client.get("/api/v1/agents", headers=h(w, "unverified", org))
            assert response.status_code == 403
            assert response.json() == {"detail": "Email verification required."}
        listed = w.client.get("/api/v1/organizations", headers=h(w, "unverified"))
        assert listed.status_code == 403


# --- /auth/me and GET /organizations ---------------------------------------------------------


def test_me_lists_memberships_and_reflects_only_valid_selection() -> None:
    with world() as w:
        plain = w.client.get("/api/v1/auth/me", headers=h(w, "dual")).json()
        assert sorted(m["organization"]["slug"] for m in plain["organization_memberships"]) == [
            "org-a",
            "org-b",
        ]
        assert plain["organization_membership"] is None
        assert plain["selected_organization_id"] is None

        chosen = w.client.get("/api/v1/auth/me", headers=h(w, "dual", "b")).json()
        assert chosen["selected_organization_id"] == str(w.org["b"])
        assert chosen["organization_membership"]["role"] == "auditor"
        assert chosen["organization_membership"]["organization"]["id"] == str(w.org["b"])

        for bad in ("c", "d", uuid4(), "garbage"):
            response = w.client.get("/api/v1/auth/me", headers=h(w, "dual", bad))
            assert response.status_code == 200
            body = response.json()
            assert body["selected_organization_id"] is None
            assert body["organization_membership"] is None
            assert len(body["organization_memberships"]) == 2


def test_me_for_single_and_no_membership_users() -> None:
    with world() as w:
        single = w.client.get("/api/v1/auth/me", headers=h(w, "single")).json()
        assert single["selected_organization_id"] == str(w.org["a"])
        assert single["organization_membership"]["role"] == "operator"
        foreign = w.client.get("/api/v1/auth/me", headers=h(w, "single", "b")).json()
        assert foreign["organization_membership"] is None
        nobody = w.client.get("/api/v1/auth/me", headers=h(w, "none")).json()
        assert nobody["organization_memberships"] == []
        assert nobody["organization_membership"] is None


def test_list_organizations_returns_only_own_active_memberships() -> None:
    with world() as w:
        dual = w.client.get("/api/v1/organizations", headers=h(w, "dual", uuid4()))
        assert dual.status_code == 200
        body = dual.json()
        assert body["total"] == 2
        assert sorted((item["organization"]["slug"], item["role"]) for item in body["items"]) == [
            ("org-a", "admin"),
            ("org-b", "auditor"),
        ]
        nobody = w.client.get("/api/v1/organizations", headers=h(w, "none")).json()
        assert nobody == {"items": [], "total": 0}
        assert w.client.get("/api/v1/organizations").status_code == 401


def test_member_listing_never_exposes_other_organizations() -> None:
    with world() as w:
        members = w.client.get("/api/v1/users", headers=h(w, "dual_admin", "a")).json()["items"]
        dual = next(item for item in members if item["email"] == "dual@example.com")
        assert dual["organization_memberships"] == []
        assert dual["selected_organization_id"] is None
        assert dual["organization_membership"]["organization"]["id"] == str(w.org["a"])


# --- Gateway -----------------------------------------------------------------------------------


def test_gateway_tokens_ignore_the_user_organization_header() -> None:
    with world() as w:
        servers = {}
        for key, admin in (("a", "admin_a"), ("b", "admin_b")):
            server = w.client.post(
                "/api/v1/mcp-servers",
                headers=h(w, admin),
                json={"name": f"Gateway {key}", "server_url": f"https://{key}.example.com/mcp"},
            ).json()
            w.client.post(f"/api/v1/mcp-servers/{server['id']}/sync", headers=h(w, admin))
            servers[key] = server["id"]
        token_a = w.client.post(
            "/api/v1/mcp-gateway-tokens",
            headers=h(w, "admin_a"),
            json={"mcp_server_id": servers["a"], "name": "Org A token"},
        ).json()["token"]
        gateway = {"Authorization": f"Bearer {token_a}", HEADER: str(w.org["b"])}

        own = w.client.get(f"/api/v1/mcp-gateway/{servers['a']}/tools", headers=gateway)
        other = w.client.get(f"/api/v1/mcp-gateway/{servers['b']}/tools", headers=gateway)
        garbage = w.client.get(
            f"/api/v1/mcp-gateway/{servers['a']}/tools",
            headers={"Authorization": f"Bearer {token_a}", HEADER: "garbage"},
        )

        assert own.status_code == 200
        assert other.status_code == 401
        assert garbage.status_code == 200


# --- Feature flag ------------------------------------------------------------------------------


@contextmanager
def multi_organization_flag(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> Iterator[None]:
    monkeypatch.setenv("MULTI_ORGANIZATION_MEMBERSHIPS_ENABLED", "true" if enabled else "false")
    get_settings.cache_clear()
    try:
        yield
    finally:
        monkeypatch.delenv("MULTI_ORGANIZATION_MEMBERSHIPS_ENABLED")
        get_settings.cache_clear()


def invite_admin_a_into_b(w: World) -> dict[str, Any]:
    response = w.client.post(
        "/api/v1/organization-invites",
        headers=h(w, "admin_b"),
        json={"email": "admin-a@example.com", "role": "operator"},
    )
    assert response.status_code == 201
    return dict(response.json())


def test_flag_defaults_to_disabled() -> None:
    get_settings.cache_clear()
    assert get_settings().multi_organization_memberships_enabled is False


def test_flag_disabled_keeps_phase0_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    with world() as w, multi_organization_flag(monkeypatch, enabled=False):
        invite = invite_admin_a_into_b(w)
        response = w.client.post(
            "/api/v1/organization-invites/accept",
            json={"token": invite["token"], "password": PASSWORD},
        )
        assert response.status_code == 409
        assert response.json() == {"detail": "Multiple organizations are not yet supported."}


def test_flag_enabled_allows_second_membership_with_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with world() as w, multi_organization_flag(monkeypatch, enabled=True):
        invite = invite_admin_a_into_b(w)
        accepted = w.client.post(
            "/api/v1/organization-invites/accept",
            json={"token": invite["token"], "password": PASSWORD},
        )
        assert accepted.status_code == 200
        user = accepted.json()["user"]
        # The response selects the organization just joined.
        assert user["selected_organization_id"] == str(w.org["b"])
        assert user["organization_membership"]["role"] == "operator"
        assert len(user["organization_memberships"]) == 2

        # Existing tokens stay valid; the user now has to choose.
        assert w.client.get("/api/v1/users", headers=h(w, "admin_a")).status_code == 409
        assert w.client.get("/api/v1/users", headers=h(w, "admin_a", "a")).status_code == 200
        assert w.client.get("/api/v1/users", headers=h(w, "admin_a", "b")).status_code == 403
        approvals = w.client.get("/api/v1/approvals", headers=h(w, "admin_a", "b"))
        assert approvals.status_code == 200  # operator permission in B

        replay = w.client.post(
            "/api/v1/organization-invites/accept",
            json={"token": invite["token"], "password": PASSWORD},
        )
        assert replay.status_code == 400


def test_bootstrap_response_selects_the_new_organization() -> None:
    with world() as w:
        with w.session_local() as db:
            for organization in db.scalars(select(Organization)).all():
                organization.deleted_at = datetime.now(UTC)
            db.commit()
        response = w.client.post(
            "/api/v1/organizations/bootstrap",
            json={
                "organization_name": "Fresh Org",
                "admin_full_name": "Fresh Admin",
                "admin_email": "fresh@example.com",
                "admin_password": PASSWORD,
            },
        )
        assert response.status_code == 201
        user = response.json()["user"]
        assert user["organization_membership"]["organization"]["name"] == "Fresh Org"
        assert (
            user["selected_organization_id"] == user["organization_membership"]["organization_id"]
        )
