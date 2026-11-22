"""MCP credential references are bound to the owning organization.

An organization administrator must never be able to make AgentHQ send another organization's
environment-backed MCP credential to an MCP server they control.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast
from uuid import UUID

import pytest
from email_helpers import database_session
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters import mcp_discovery, mcp_execution
from app.adapters.mcp_discovery import (
    DiscoveredMCPTool,
    MCPDiscoveryError,
    MCPDiscoveryTarget,
    RealMCPDiscoveryAdapter,
    build_auth_headers,
    get_mcp_discovery_adapter,
)
from app.adapters.mcp_execution import (
    MCPExecutionError,
    RealMCPExecutionAdapter,
    get_mcp_execution_adapter,
)
from app.core.mcp_credentials import (
    organization_secret_ref_prefix,
    secret_ref_belongs_to_organization,
)
from app.models.mcp_server import MCPAuthType, MCPServer
from app.models.organization import Organization

ORG_A = UUID("0a0a0a0a-1111-4111-8111-0a0a0a0a0a0a")
ORG_B = UUID("0b0b0b0b-2222-4222-8222-0b0b0b0b0b0b")
SECRET_A = "org-a-credential-value"
SECRET_B = "org-b-credential-value"
REJECTED_EVENT = "security_mcp_credential_ref_rejected"


def ref(organization_id: UUID, name: str = "CRM") -> str:
    return f"{organization_secret_ref_prefix(organization_id)}{name}"


def target(**values: object) -> MCPDiscoveryTarget:
    defaults: dict[str, object] = {"server_url": "https://mcp.example.com/mcp"}
    defaults.update(values)
    return MCPDiscoveryTarget(**defaults)  # type: ignore[arg-type]


class TransportRecorder:
    """Stands in for the network: records every connection attempt and its headers."""

    def __init__(self) -> None:
        self.headers: list[dict[str, str]] = []

    @asynccontextmanager
    async def __call__(
        self,
        mcp_target: MCPDiscoveryTarget,
        headers: dict[str, str],
    ) -> AsyncIterator[tuple[object, object]]:
        self.headers.append(dict(headers))
        yield object(), object()


class FakeToolResult:
    def model_dump(self, *, mode: str) -> dict[str, object]:
        return {"content": [{"type": "text", "text": "done"}]}


class FakeSession:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def initialize(self) -> None:
        pass

    async def list_tools(self, cursor: str | None = None) -> Any:
        raise RuntimeError("discovery session is not exercised here")

    async def call_tool(self, name: str, *, arguments: dict[str, object]) -> FakeToolResult:
        return FakeToolResult()


@pytest.fixture()
def network(monkeypatch: pytest.MonkeyPatch) -> TransportRecorder:
    recorder = TransportRecorder()
    monkeypatch.setattr(mcp_discovery, "open_mcp_transport", recorder)
    monkeypatch.setattr(mcp_execution, "open_mcp_transport", recorder)
    monkeypatch.setattr(mcp_discovery, "ClientSession", FakeSession)
    monkeypatch.setattr(mcp_execution, "ClientSession", FakeSession)
    return recorder


@pytest.fixture()
def secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ref(ORG_A), SECRET_A)
    monkeypatch.setenv(ref(ORG_B), SECRET_B)
    monkeypatch.setenv("MCP_AUTH_CRM", SECRET_B)  # a legacy, unscoped variable


# --- The naming rule -----------------------------------------------------------------------


def test_reference_belongs_only_to_its_own_organization() -> None:
    assert ref(ORG_A) == f"MCP_AUTH_{ORG_A.hex.upper()}_CRM"
    assert secret_ref_belongs_to_organization(ref(ORG_A), ORG_A)
    assert secret_ref_belongs_to_organization(ref(ORG_A, "CRM_PROD_2"), ORG_A)

    assert not secret_ref_belongs_to_organization(ref(ORG_B), ORG_A)
    assert not secret_ref_belongs_to_organization("MCP_AUTH_CRM", ORG_A)
    assert not secret_ref_belongs_to_organization(organization_secret_ref_prefix(ORG_A), ORG_A)
    assert not secret_ref_belongs_to_organization(f"MCP_AUTH_{ORG_A.hex}_CRM", ORG_A)
    assert not secret_ref_belongs_to_organization(f"MCP_AUTH_{ORG_A}_CRM", ORG_A)
    assert not secret_ref_belongs_to_organization(ref(ORG_A, "CRM-PROD"), ORG_A)
    assert not secret_ref_belongs_to_organization(ref(ORG_A, "X" * 255), ORG_A)


# --- Resolution: discovery and execution share one boundary -------------------------------


@pytest.mark.usefixtures("secrets")
@pytest.mark.parametrize(
    ("auth_type", "expected"),
    [
        (MCPAuthType.BEARER, {"Authorization": f"Bearer {SECRET_A}"}),
        (MCPAuthType.API_KEY, {"X-API-Key": SECRET_A}),
    ],
)
def test_organization_resolves_its_own_credential(
    auth_type: MCPAuthType,
    expected: dict[str, str],
) -> None:
    headers = build_auth_headers(
        target(auth_type=auth_type, auth_secret_ref=ref(ORG_A), organization_id=ORG_A)
    )

    assert headers == expected


@pytest.mark.usefixtures("secrets")
@pytest.mark.parametrize(
    ("secret_ref", "organization_id"),
    [
        (ref(ORG_B), ORG_A),  # another organization's credential
        ("MCP_AUTH_CRM", ORG_A),  # legacy unscoped reference
        (ref(ORG_A), None),  # no owning organization supplied
    ],
)
def test_foreign_legacy_or_unowned_reference_is_refused(
    secret_ref: str,
    organization_id: UUID | None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="agenthq.security"):
        with pytest.raises(MCPDiscoveryError) as error:
            build_auth_headers(
                target(
                    auth_type=MCPAuthType.BEARER,
                    auth_secret_ref=secret_ref,
                    organization_id=organization_id,
                )
            )

    assert str(error.value) == "MCP authentication is not configured."
    assert REJECTED_EVENT in caplog.text
    for value in (SECRET_A, SECRET_B, secret_ref):
        assert value not in str(error.value)
        assert value not in caplog.text


@pytest.mark.usefixtures("secrets")
def test_discovery_and_execution_send_own_credential(network: TransportRecorder) -> None:
    own = target(auth_type=MCPAuthType.BEARER, auth_secret_ref=ref(ORG_A), organization_id=ORG_A)

    with pytest.raises(MCPDiscoveryError):  # the fake session stops after connecting
        RealMCPDiscoveryAdapter().discover_tools(own)
    result = RealMCPExecutionAdapter().call_tool(own, "lookup", {})

    assert network.headers == [
        {"Authorization": f"Bearer {SECRET_A}"},
        {"Authorization": f"Bearer {SECRET_A}"},
    ]
    assert result.payload["content"] == [{"type": "text", "text": "done"}]


@pytest.mark.usefixtures("secrets")
@pytest.mark.parametrize("secret_ref", [ref(ORG_B), "MCP_AUTH_CRM"])
def test_discovery_and_execution_make_no_request_for_foreign_reference(
    network: TransportRecorder,
    secret_ref: str,
) -> None:
    foreign = target(
        auth_type=MCPAuthType.BEARER, auth_secret_ref=secret_ref, organization_id=ORG_A
    )

    with pytest.raises(MCPDiscoveryError):
        RealMCPDiscoveryAdapter().discover_tools(foreign)
    with pytest.raises(MCPExecutionError):
        RealMCPExecutionAdapter().call_tool(foreign, "lookup", {})

    assert network.headers == []


# --- Configuration: create and update ------------------------------------------------------


def organization_id(client: TestClient) -> UUID:
    """The test client's single active organization."""
    with database_session(client) as db:
        organization = db.scalar(select(Organization.id).where(Organization.deleted_at.is_(None)))
    assert organization is not None
    return organization


def server_payload(**values: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "CRM MCP",
        "server_url": "https://mcp.example.com/server",
    }
    payload.update(values)
    return payload


def test_create_accepts_own_organization_reference(client: TestClient) -> None:
    own = ref(organization_id(client))

    response = client.post(
        "/api/v1/mcp-servers",
        json=server_payload(auth_type="bearer", auth_secret_ref=own),
    )

    assert response.status_code == 201
    assert response.json()["auth_secret_ref"] == own


@pytest.mark.parametrize("secret_ref", [ref(ORG_B), "MCP_AUTH_CRM"])
def test_create_rejects_foreign_or_legacy_reference(
    client: TestClient,
    secret_ref: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="agenthq.security"):
        response = client.post(
            "/api/v1/mcp-servers",
            json=server_payload(auth_type="bearer", auth_secret_ref=secret_ref),
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "MCP authentication configuration is invalid."}
    assert client.get("/api/v1/mcp-servers").json()["total"] == 0
    assert REJECTED_EVENT in caplog.text
    assert secret_ref not in caplog.text


@pytest.mark.parametrize("secret_ref", [ref(ORG_B), "MCP_AUTH_CRM"])
def test_update_rejects_foreign_or_legacy_reference(client: TestClient, secret_ref: str) -> None:
    own = ref(organization_id(client))
    server = client.post(
        "/api/v1/mcp-servers",
        json=server_payload(auth_type="bearer", auth_secret_ref=own),
    ).json()

    response = client.patch(
        f"/api/v1/mcp-servers/{server['id']}",
        json={"auth_secret_ref": secret_ref},
    )

    assert response.status_code == 422
    assert client.get(f"/api/v1/mcp-servers/{server['id']}").json()["auth_secret_ref"] == own


# --- Persisted cross-tenant references are blocked when used --------------------------------


class ToolDiscovery:
    def discover_tools(self, mcp_target: MCPDiscoveryTarget) -> list[DiscoveredMCPTool]:
        return [DiscoveredMCPTool("lookup", "Look up a record.", input_schema={"type": "object"})]


def gateway_with_credential(client: TestClient, secret_ref: str) -> dict[str, Any]:
    """A governed, callable tool on an authenticated MCP server, as an administrator sets it up."""
    app = cast(FastAPI, client.app)
    server = client.post(
        "/api/v1/mcp-servers",
        json=server_payload(auth_type="bearer", auth_secret_ref=secret_ref),
    ).json()
    app.dependency_overrides[get_mcp_discovery_adapter] = lambda: ToolDiscovery()
    assert client.post(f"/api/v1/mcp-servers/{server['id']}/sync").status_code == 200
    tool = client.get("/api/v1/tool-governance").json()["items"][0]
    assert (
        client.post(
            f"/api/v1/tool-governance/{tool['id']}/review",
            json={"risk_level": "medium", "permission": "execute"},
        ).status_code
        == 200
    )
    token = client.post(
        "/api/v1/mcp-gateway-tokens",
        json={"mcp_server_id": server["id"], "name": "Isolation test client"},
    ).json()["token"]
    app.dependency_overrides[get_mcp_execution_adapter] = lambda: RealMCPExecutionAdapter()
    return {"app": app, "server": server, "tool": tool, "token": token}


def call_gateway_tool(client: TestClient, setup: dict[str, Any]) -> Any:
    return client.post(
        f"/api/v1/mcp-gateway/{setup['server']['id']}/tools/{setup['tool']['id']}/call",
        headers={"Authorization": f"Bearer {setup['token']}"},
        json={"input_payload": {"record": "1"}},
    )


def plant_reference(client: TestClient, server_id: str, secret_ref: str) -> None:
    """Simulate a legacy or tampered record that never passed the new validation."""
    with database_session(client) as db:
        server = db.get(MCPServer, UUID(server_id))
        assert server is not None
        server.auth_type = MCPAuthType.BEARER
        server.auth_secret_ref = secret_ref
        db.commit()


@pytest.mark.usefixtures("secrets")
def test_valid_credential_backed_gateway_call_still_works(
    client: TestClient,
    network: TransportRecorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    own = ref(organization_id(client))
    monkeypatch.setenv(own, SECRET_A)
    setup = gateway_with_credential(client, own)

    response = call_gateway_tool(client, setup)

    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"
    assert network.headers == [{"Authorization": f"Bearer {SECRET_A}"}]


@pytest.mark.usefixtures("secrets")
@pytest.mark.parametrize("planted", [ref(ORG_B), "MCP_AUTH_CRM"])
def test_persisted_foreign_reference_is_blocked_at_execution_and_discovery(
    client: TestClient,
    network: TransportRecorder,
    monkeypatch: pytest.MonkeyPatch,
    planted: str,
) -> None:
    own = ref(organization_id(client))
    monkeypatch.setenv(own, SECRET_A)
    setup = gateway_with_credential(client, own)
    plant_reference(client, setup["server"]["id"], planted)

    call = call_gateway_tool(client, setup)
    setup["app"].dependency_overrides[get_mcp_discovery_adapter] = lambda: RealMCPDiscoveryAdapter()
    sync = client.post(f"/api/v1/mcp-servers/{setup['server']['id']}/sync")
    edit = client.patch(f"/api/v1/mcp-servers/{setup['server']['id']}", json={"name": "Renamed"})
    audit = client.get("/api/v1/audit-logs", params={"limit": 100}).text

    assert call.status_code == 200
    assert call.json()["status"] == "failed"
    assert call.json()["error"] == "Upstream MCP tool call failed."
    assert sync.status_code == 502
    assert edit.status_code == 422
    assert network.headers == []  # no outbound request was made at all
    for text in (call.text, sync.text, audit):
        assert SECRET_A not in text
        assert SECRET_B not in text
