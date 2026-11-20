"""Gateway credentials must stop working when their organization is soft-deleted.

Gateway tokens carry their own organization (mcp_gateway_tokens.organization_id); the user
organization header never applies to them. These tests cover both gateway dependencies (per-server
tokens and agent credentials, including the MCP protocol endpoint) and check that a deleted
organization's credential is refused exactly like an invalid one, without changing the credential
or creating any tenant resource.
"""

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from test_mcp_gateway import DiscoveryAdapter, ExecutionAdapter
from test_organization_context import HEADER, World, h, world

from app.adapters.mcp_discovery import get_mcp_discovery_adapter
from app.adapters.mcp_execution import get_mcp_execution_adapter
from app.models.approval import Approval
from app.models.audit_log import AuditAction, AuditLog, AuditOutcome
from app.models.execution import Execution
from app.models.mcp_gateway import MCPGatewayCallRecord, MCPGatewayToken
from app.models.organization import Organization

INVALID_TOKEN = {"detail": "Invalid gateway token."}  # per-server token routes
INVALID_CREDENTIAL = {"detail": "Invalid gateway credential."}  # agent credential routes


def bearer(raw: str, organization: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {raw}"}
    if organization is not None:
        headers[HEADER] = organization
    return headers


def provision(w: World, key: str, admin: str) -> dict[str, Any]:
    """A reviewed, executable tool behind an MCP server, a per-server token and an agent
    credential, all created by the organization's admin through the API."""
    server = w.client.post(
        "/api/v1/mcp-servers",
        headers=h(w, admin),
        json={"name": f"Gateway {key}", "server_url": f"https://{key}.example.com/mcp"},
    ).json()
    assert (
        w.client.post(f"/api/v1/mcp-servers/{server['id']}/sync", headers=h(w, admin)).status_code
        == 200
    )
    tool = w.client.get("/api/v1/tool-governance", headers=h(w, admin)).json()["items"][0]
    review = w.client.post(
        f"/api/v1/tool-governance/{tool['id']}/review",
        headers=h(w, admin),
        json={"risk_level": "low", "permission": "execute"},
    )
    assert review.status_code == 200, review.text
    token = w.client.post(
        "/api/v1/mcp-gateway-tokens",
        headers=h(w, admin),
        json={"mcp_server_id": server["id"], "name": f"Org {key} token"},
    )
    assert token.status_code == 201, token.text
    credential = w.client.post(
        "/api/v1/agent-gateway-credentials",
        headers=h(w, admin),
        json={
            "agent_id": tool["agent_id"],
            "allowed_mcp_server_ids": [server["id"]],
            "name": f"Org {key} runtime",
        },
    )
    assert credential.status_code == 201, credential.text
    return {
        "server": server["id"],
        "tool": tool["id"],
        "token": token.json()["token"],
        "token_id": token.json()["id"],
        "credential": credential.json()["token"],
        "credential_id": credential.json()["id"],
    }


def gateway_requests(g: dict[str, Any], organization: str | None = None) -> dict[str, Any]:
    """Every gateway entry point: both dependencies and the MCP protocol endpoint."""
    server, tool, token, credential = g["server"], g["tool"], g["token"], g["credential"]
    return {
        "token: info": (
            "GET",
            f"/api/v1/mcp-gateway/{server}/info",
            bearer(token, organization),
            None,
        ),
        "token: tools": (
            "GET",
            f"/api/v1/mcp-gateway/{server}/tools",
            bearer(token, organization),
            None,
        ),
        "token: call": (
            "POST",
            f"/api/v1/mcp-gateway/{server}/tools/{tool}/call",
            bearer(token, organization),
            {"input_payload": {"account_id": "1"}, "idempotency_key": f"k-{uuid4()}"},
        ),
        "credential: servers": (
            "GET",
            "/api/v1/gateway/mcp-servers",
            bearer(credential, organization),
            None,
        ),
        "credential: tools": (
            "GET",
            f"/api/v1/gateway/mcp-servers/{server}/tools",
            bearer(credential, organization),
            None,
        ),
        "credential: mcp tools/list": (
            "POST",
            f"/api/v1/mcp/{server}",
            bearer(credential, organization),
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        ),
        "credential: mcp tools/call": (
            "POST",
            f"/api/v1/mcp/{server}",
            bearer(credential, organization),
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "transfer_funds", "arguments": {"account_id": "1"}},
            },
        ),
    }


def send(w: World, request: tuple[str, str, dict[str, str], Any]) -> Any:
    method, url, headers, body = request
    return w.client.request(method, url, headers=headers, json=body)


def soft_delete(w: World, key: str) -> None:
    with w.session_local() as db:
        organization = db.get(Organization, w.org[key])
        assert organization is not None
        organization.deleted_at = datetime.now(UTC)
        db.commit()


def credential_rows(w: World, organization_id: UUID) -> list[tuple[Any, ...]]:
    with w.session_local() as db:
        rows = db.scalars(
            select(MCPGatewayToken)
            .where(MCPGatewayToken.organization_id == organization_id)
            .order_by(MCPGatewayToken.id)
        ).all()
        return [
            (
                r.id,
                r.organization_id,
                r.agent_id,
                r.mcp_server_id,
                r.name,
                r.token_hash,
                r.status,
                r.expires_at,
                r.last_used_at,
                r.created_by_user_id,
            )
            for r in rows
        ]


def tenant_counts(w: World, organization_id: UUID) -> dict[str, int]:
    with w.session_local() as db:
        return {
            model.__name__: int(
                db.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.organization_id == organization_id)
                )
                or 0
            )
            for model in (Execution, Approval, MCPGatewayCallRecord)
        }


def with_adapters(w: World) -> ExecutionAdapter:
    app = cast(FastAPI, w.client.app)
    app.dependency_overrides[get_mcp_discovery_adapter] = lambda: DiscoveryAdapter()
    upstream = ExecutionAdapter()
    app.dependency_overrides[get_mcp_execution_adapter] = lambda: upstream
    return upstream


def test_deleted_organization_gateway_credentials_are_refused_like_invalid_ones() -> None:
    with world() as w:
        upstream = with_adapters(w)
        a = provision(w, "a", "admin_a")
        b = provision(w, "b", "admin_b")
        # While Org A is active, every gateway entry point accepts its credentials.
        for name, request in gateway_requests(a).items():
            if name.endswith("call"):
                continue  # read-only probes; tool calls are only attempted after deletion
            assert send(w, request).status_code == 200, name

        soft_delete(w, "a")
        rows_before = credential_rows(w, w.org["a"])
        counts_before = tenant_counts(w, w.org["a"])
        unknown = {
            "token": w.client.get(
                f"/api/v1/mcp-gateway/{a['server']}/tools", headers=bearer("aghq_unknown")
            ),
            "credential": w.client.get(
                "/api/v1/gateway/mcp-servers", headers=bearer("aghq_unknown")
            ),
        }

        for name, request in gateway_requests(a).items():
            response = send(w, request)
            expected = INVALID_TOKEN if name.startswith("token") else INVALID_CREDENTIAL
            reference = unknown["token" if name.startswith("token") else "credential"]
            assert response.status_code == 401, name
            assert response.json() == expected, name
            # Byte-identical to an unknown token: nothing reveals that the organization existed.
            assert response.content == reference.content, name

        # Nothing was created, called or changed for the deleted organization.
        assert upstream.calls == 0
        assert tenant_counts(w, w.org["a"]) == counts_before
        assert credential_rows(w, w.org["a"]) == rows_before  # status and last_used_at untouched

        # Another organization's credentials keep working.
        for name, request in gateway_requests(b).items():
            if not name.endswith("call"):
                assert send(w, request).status_code == 200, name


def test_deleted_organization_denials_are_audited_only_in_that_organization() -> None:
    with world() as w:
        with_adapters(w)
        a = provision(w, "a", "admin_a")
        provision(w, "b", "admin_b")
        soft_delete(w, "a")

        def count(*where: Any) -> int:
            with w.session_local() as db:
                return int(db.scalar(select(func.count()).select_from(AuditLog).where(*where)) or 0)

        token_id = UUID(a["token_id"])
        used = (
            AuditLog.action == AuditAction.AGENT_GATEWAY_CREDENTIAL_USED,
            AuditLog.entity_id == token_id,
        )
        used_before, b_before = count(*used), count(AuditLog.organization_id == w.org["b"])
        w.client.get(
            f"/api/v1/mcp-gateway/{a['server']}/tools", headers=bearer(a["token"], str(w.org["b"]))
        )
        with w.session_local() as db:
            denied = db.scalars(
                select(AuditLog).where(
                    AuditLog.action == AuditAction.AGENT_GATEWAY_CREDENTIAL_DENIED
                )
            ).all()
        assert [(r.organization_id, r.entity_id, r.outcome) for r in denied] == [
            (w.org["a"], token_id, AuditOutcome.DENIED)
        ]
        assert count(*used) == used_before  # the refused attempt is never recorded as a use
        b_after = count(AuditLog.organization_id == w.org["b"])
        assert b_after == b_before  # a foreign header never moves the event into Org B


def test_invalid_revoked_and_foreign_credentials_stay_refused() -> None:
    with world() as w:
        with_adapters(w)
        a = provision(w, "a", "admin_a")
        b = provision(w, "b", "admin_b")
        tools = "/api/v1/mcp-gateway/{server}/tools"
        # A token from one active organization never reaches another organization's server.
        assert (
            w.client.get(tools.format(server=b["server"]), headers=bearer(a["token"])).status_code
            == 401
        )
        assert (
            w.client.get(tools.format(server=a["server"]), headers=bearer(b["token"])).status_code
            == 401
        )
        assert w.client.get(
            f"/api/v1/gateway/mcp-servers/{b['server']}/tools", headers=bearer(a["credential"])
        ).status_code in (401, 404)
        # Invalid token, and no Authorization header at all.
        assert (
            w.client.get(tools.format(server=a["server"]), headers=bearer("aghq_invalid")).json()
            == INVALID_TOKEN
        )
        assert w.client.get(tools.format(server=a["server"])).status_code == 401
        # Revoked.
        assert (
            w.client.post(
                f"/api/v1/mcp-gateway-tokens/{a['token_id']}/revoke", headers=h(w, "admin_a")
            ).status_code
            == 200
        )
        assert (
            w.client.get(tools.format(server=a["server"]), headers=bearer(a["token"])).json()
            == INVALID_TOKEN
        )
        # Expiry is covered on PostgreSQL below: SQLite returns timezone-naive timestamps, which
        # the existing expiry comparison cannot compare (PostgreSQL timestamptz is always aware).


def test_organization_header_never_affects_gateway_credentials() -> None:
    with world() as w:
        with_adapters(w)
        a = provision(w, "a", "admin_a")
        b = provision(w, "b", "admin_b")
        tools_b = f"/api/v1/mcp-gateway/{b['server']}/tools"
        # Active credential: malformed, foreign or deleted-organization headers are ignored.
        for header in ("not-a-uuid", str(w.org["a"]), str(w.org["d"]), str(uuid4())):
            assert w.client.get(tools_b, headers=bearer(b["token"], header)).status_code == 200, (
                header
            )
        # Deleted organization's credential: no header (its own or another) revives it.
        soft_delete(w, "a")
        for header in (str(w.org["a"]), str(w.org["b"]), "not-a-uuid"):
            response = w.client.get(
                f"/api/v1/mcp-gateway/{a['server']}/tools", headers=bearer(a["token"], header)
            )
            assert response.status_code == 401 and response.json() == INVALID_TOKEN, header
            response = w.client.get(
                "/api/v1/gateway/mcp-servers", headers=bearer(a["credential"], header)
            )
            assert response.status_code == 401 and response.json() == INVALID_CREDENTIAL, header


# --- PostgreSQL (opt-in, like the other *_postgres tests): expiry and deletion on timestamptz ---

ADMIN_URL = os.environ.get("AGENTHQ_TEST_POSTGRES_URL")


@pytest.mark.skipif(
    not ADMIN_URL, reason="set AGENTHQ_TEST_POSTGRES_URL to a disposable PostgreSQL server"
)
def test_postgres_deleted_organization_and_expired_tokens_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alembic.config import Config
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session, sessionmaker

    from alembic import command
    from app.core.config import get_settings
    from app.core.rate_limit import reset_rate_limit_backend
    from app.core.security import create_access_token, hash_password
    from app.db.session import get_db
    from app.main import create_app
    from app.models.organization import OrganizationMembership
    from app.models.user import User, UserRole

    assert ADMIN_URL is not None
    name = f"agenthq_gateway_{uuid4().hex[:8]}"
    url = make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)
    admin_engine = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    engine = None
    try:
        monkeypatch.setenv("DATABASE_URL", url)
        monkeypatch.setenv("REDIS_URL", "")
        monkeypatch.setenv("MCP_DISCOVERY_MODE", "mock")
        get_settings.cache_clear()
        reset_rate_limit_backend()
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
        command.upgrade(config, "head")
        engine = create_engine(url)
        session = sessionmaker(bind=engine, autoflush=False)
        admins: dict[str, str] = {}
        orgs: dict[str, UUID] = {}
        with session() as db:
            for key in ("a", "b"):
                organization = Organization(name=f"Org {key}", slug=f"org-{key}")
                admin = User(
                    email=f"admin-{key}@example.com",
                    full_name=key,
                    password_hash=hash_password("GatewayPassword123!"),
                    role=UserRole.ADMIN,
                )
                db.add_all([organization, admin])
                db.flush()
                db.add(
                    OrganizationMembership(
                        organization_id=organization.id, user_id=admin.id, role=UserRole.ADMIN
                    )
                )
                db.flush()
                admins[key], orgs[key] = create_access_token(admin), organization.id
            db.commit()

        def override_get_db() -> Iterator[Session]:
            with session() as db:
                yield db

        app = create_app()
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_mcp_discovery_adapter] = lambda: DiscoveryAdapter()
        with TestClient(app) as client:

            def issue(key: str, label: str) -> tuple[str, str, str]:
                auth = {"Authorization": f"Bearer {admins[key]}"}
                server = client.post(
                    "/api/v1/mcp-servers",
                    headers=auth,
                    json={"name": f"{label}", "server_url": f"https://{label}.example.com/mcp"},
                ).json()["id"]
                assert (
                    client.post(f"/api/v1/mcp-servers/{server}/sync", headers=auth).status_code
                    == 200
                )
                created = client.post(
                    "/api/v1/mcp-gateway-tokens",
                    headers=auth,
                    json={"mcp_server_id": server, "name": label},
                )
                assert created.status_code == 201, created.text
                return server, created.json()["token"], created.json()["id"]

            server_a, token_a, _ = issue("a", "gw-a")
            server_b, token_b, token_b_id = issue("b", "gw-b")
            server_b2, token_b2, _ = issue("b", "gw-b2")

            def tools(server: str, raw: str) -> Any:
                return client.get(f"/api/v1/mcp-gateway/{server}/tools", headers=bearer(raw))

            assert tools(server_a, token_a).status_code == 200
            # Expired (timestamptz): refused with the generic body.
            with session() as db:
                row = db.get(MCPGatewayToken, UUID(token_b_id))
                assert row is not None
                row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
                db.commit()
            assert tools(server_b, token_b).json() == INVALID_TOKEN
            # Deleted organization: refused like an unknown token; the other org still works.
            with session() as db:
                deleted_org = db.get(Organization, orgs["a"])
                assert deleted_org is not None
                deleted_org.deleted_at = datetime.now(UTC)
                db.commit()
            refused = tools(server_a, token_a)
            assert refused.status_code == 401
            assert refused.content == tools(server_a, "aghq_unknown").content
            assert tools(server_b2, token_b2).status_code == 200
            with session() as db:
                statuses = {t.name: t.status.value for t in db.scalars(select(MCPGatewayToken))}
            assert statuses == {
                "gw-a": "active",
                "gw-b": "active",
                "gw-b2": "active",
            }  # never mutated
    finally:
        get_settings.cache_clear()
        reset_rate_limit_backend()
        if engine is not None:
            engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin_engine.dispose()
