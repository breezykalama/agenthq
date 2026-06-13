from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, cast
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.rate_limit import rate_limiter
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.models.agent import Agent, AgentRiskLevel
from app.models.agent_tool import AgentTool, AgentToolPermission
from app.models.governance_alert import (
    GovernanceAlert,
    GovernanceAlertSeverity,
    GovernanceAlertType,
)
from app.models.organization import Organization, OrganizationMembership
from app.models.user import User, UserRole


@dataclass(frozen=True)
class TenantClients:
    client: TestClient
    headers_a: dict[str, str]
    headers_b: dict[str, str]
    organization_a_id: str
    organization_b_id: str
    session_local: sessionmaker[Session]


@contextmanager
def tenant_clients() -> Iterator[TenantClients]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(engine)
    with session_local() as db:
        organization_a = Organization(name="Organization A", slug="organization-a")
        organization_b = Organization(name="Organization B", slug="organization-b")
        user_a = User(
            email="admin-a@example.com",
            full_name="Admin A",
            password_hash=hash_password("StrongPassword123!"),
            role=UserRole.ADMIN,
        )
        user_b = User(
            email="admin-b@example.com",
            full_name="Admin B",
            password_hash=hash_password("StrongPassword123!"),
            role=UserRole.ADMIN,
        )
        db.add_all([organization_a, organization_b, user_a, user_b])
        db.flush()
        db.add_all(
            [
                OrganizationMembership(
                    organization_id=organization_a.id,
                    user_id=user_a.id,
                    role=UserRole.ADMIN,
                ),
                OrganizationMembership(
                    organization_id=organization_b.id,
                    user_id=user_b.id,
                    role=UserRole.ADMIN,
                ),
            ]
        )
        db.commit()
        token_a = create_access_token(user_a)
        token_b = create_access_token(user_b)
        organization_a_id = str(organization_a.id)
        organization_b_id = str(organization_b.id)

    def override_get_db() -> Iterator[Session]:
        with session_local() as db:
            yield db

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    with (
        patch("app.core.rate_limit.get_rate_limit_backend", return_value=rate_limiter),
        TestClient(app) as client,
    ):
        yield TenantClients(
            client=client,
            headers_a={"Authorization": f"Bearer {token_a}"},
            headers_b={"Authorization": f"Bearer {token_b}"},
            organization_a_id=organization_a_id,
            organization_b_id=organization_b_id,
            session_local=session_local,
        )
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def create_agent(client: TestClient, headers: dict[str, str], name: str) -> dict[str, Any]:
    response = client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": name,
            "owner": "owner@example.com",
            "department": "governance",
            "risk_level": "low",
        },
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def create_tenant_user(
    tenants: TenantClients,
    *,
    organization_id: str,
    email: str,
    role: UserRole,
    is_active: bool = True,
) -> dict[str, str]:
    with tenants.session_local() as db:
        user = User(
            email=email,
            full_name=email,
            password_hash=hash_password("StrongPassword123!"),
            role=UserRole.AGENT_OWNER,
        )
        db.add(user)
        db.flush()
        db.add(
            OrganizationMembership(
                organization_id=UUID(organization_id),
                user_id=user.id,
                role=role,
                is_active=is_active,
            )
        )
        db.commit()
        token = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


def test_agents_are_created_and_read_within_current_organization() -> None:
    with tenant_clients() as tenants:
        agent_a = create_agent(tenants.client, tenants.headers_a, "Shared Agent Name")
        agent_b = create_agent(tenants.client, tenants.headers_b, "Shared Agent Name")

        list_a = tenants.client.get("/api/v1/agents", headers=tenants.headers_a)
        get_cross_tenant = tenants.client.get(
            f"/api/v1/agents/{agent_b['id']}",
            headers=tenants.headers_a,
        )

        assert list_a.json()["total"] == 1
        assert list_a.json()["items"][0]["id"] == agent_a["id"]
        assert get_cross_tenant.status_code == 404
        with tenants.session_local() as db:
            persisted_a = db.scalar(select(Agent).where(Agent.id == UUID(agent_a["id"])))
            persisted_b = db.scalar(select(Agent).where(Agent.id == UUID(agent_b["id"])))
            assert persisted_a is not None
            assert persisted_b is not None
            assert str(persisted_a.organization_id) == tenants.organization_a_id
            assert str(persisted_b.organization_id) == tenants.organization_b_id


def test_request_organization_id_is_ignored_and_cross_tenant_references_rejected() -> None:
    with tenant_clients() as tenants:
        agent_b = create_agent(tenants.client, tenants.headers_b, "Organization B Agent")
        injected = tenants.client.post(
            "/api/v1/agents",
            headers=tenants.headers_a,
            json={
                "organization_id": tenants.organization_b_id,
                "name": "Injected Organization Agent",
                "owner": "owner@example.com",
                "department": "governance",
                "risk_level": "low",
            },
        )
        tool = tenants.client.post(
            f"/api/v1/agents/{agent_b['id']}/tools",
            headers=tenants.headers_a,
            json={"name": "cross_tenant_tool", "permission": "execute", "risk_level": "medium"},
        )
        execution = tenants.client.post(
            "/api/v1/executions",
            headers=tenants.headers_a,
            json={
                "agent_id": agent_b["id"],
                "action_name": "cross_tenant_action",
                "risk_level": "low",
            },
        )

        assert injected.status_code == 201
        assert tool.status_code == 404
        assert execution.status_code == 404
        with tenants.session_local() as db:
            persisted = db.scalar(select(Agent).where(Agent.id == UUID(injected.json()["id"])))
            assert persisted is not None
            assert str(persisted.organization_id) == tenants.organization_a_id


def test_tool_governance_is_tenant_scoped() -> None:
    with tenant_clients() as tenants:
        agent_a = create_agent(tenants.client, tenants.headers_a, "Governance A")
        agent_b = create_agent(tenants.client, tenants.headers_b, "Governance B")
        server_a = tenants.client.post(
            "/api/v1/mcp-servers",
            headers=tenants.headers_a,
            json={"name": "MCP A", "server_url": "https://a.example.com/mcp"},
        ).json()
        server_b = tenants.client.post(
            "/api/v1/mcp-servers",
            headers=tenants.headers_b,
            json={"name": "MCP B", "server_url": "https://b.example.com/mcp"},
        ).json()
        with tenants.session_local() as db:
            db.add_all(
                [
                    AgentTool(
                        organization_id=UUID(tenants.organization_a_id),
                        agent_id=UUID(agent_a["id"]),
                        discovered_from_mcp_server_id=UUID(server_a["id"]),
                        name="tool_a",
                        permission=AgentToolPermission.EXECUTE,
                        risk_level=AgentRiskLevel.MEDIUM,
                    ),
                    AgentTool(
                        organization_id=UUID(tenants.organization_b_id),
                        agent_id=UUID(agent_b["id"]),
                        discovered_from_mcp_server_id=UUID(server_b["id"]),
                        name="tool_b",
                        permission=AgentToolPermission.EXECUTE,
                        risk_level=AgentRiskLevel.MEDIUM,
                    ),
                ]
            )
            db.commit()

        response = tenants.client.get("/api/v1/tool-governance", headers=tenants.headers_a)

        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["name"] == "tool_a"


def test_governance_alerts_are_tenant_scoped() -> None:
    with tenant_clients() as tenants:
        with tenants.session_local() as db:
            alert_a = GovernanceAlert(
                organization_id=UUID(tenants.organization_a_id),
                alert_type=GovernanceAlertType.UNGOVERNED_TOOL,
                severity=GovernanceAlertSeverity.HIGH,
                title="Organization A alert",
                description="Only organization A can read this.",
            )
            alert_b = GovernanceAlert(
                organization_id=UUID(tenants.organization_b_id),
                alert_type=GovernanceAlertType.UNGOVERNED_TOOL,
                severity=GovernanceAlertSeverity.HIGH,
                title="Organization B alert",
                description="Only organization B can read this.",
            )
            db.add_all([alert_a, alert_b])
            db.commit()
            alert_b_id = alert_b.id

        response = tenants.client.get("/api/v1/governance-alerts", headers=tenants.headers_a)
        cross_tenant = tenants.client.get(
            f"/api/v1/governance-alerts/{alert_b_id}",
            headers=tenants.headers_a,
        )

        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["title"] == "Organization A alert"
        assert cross_tenant.status_code == 404


def test_gateway_token_cannot_access_another_organization_server() -> None:
    with tenant_clients() as tenants:
        server_a = tenants.client.post(
            "/api/v1/mcp-servers",
            headers=tenants.headers_a,
            json={"name": "Gateway A", "server_url": "https://a.example.com/mcp"},
        ).json()
        server_b = tenants.client.post(
            "/api/v1/mcp-servers",
            headers=tenants.headers_b,
            json={"name": "Gateway B", "server_url": "https://b.example.com/mcp"},
        ).json()
        token_a = tenants.client.post(
            "/api/v1/mcp-gateway-tokens",
            headers=tenants.headers_a,
            json={"mcp_server_id": server_a["id"], "name": "Organization A token"},
        ).json()["token"]

        response = tenants.client.get(
            f"/api/v1/mcp-gateway/{server_b['id']}/tools",
            headers={"Authorization": f"Bearer {token_a}"},
        )

        assert response.status_code == 401


def test_policy_simulation_rejects_cross_tenant_targets() -> None:
    with tenant_clients() as tenants:
        agent_b = create_agent(tenants.client, tenants.headers_b, "Simulation Target B")

        response = tenants.client.post(
            "/api/v1/policy-simulations",
            headers=tenants.headers_a,
            json={
                "name": "Cross tenant simulation",
                "scope": "agent",
                "agent_id": agent_b["id"],
                "risk_level": "low",
                "effect": "allow",
            },
        )

        assert response.status_code == 422


def test_audit_dashboard_and_compliance_are_tenant_scoped() -> None:
    with tenant_clients() as tenants:
        create_agent(tenants.client, tenants.headers_a, "Organization A Agent")
        create_agent(tenants.client, tenants.headers_b, "Organization B Agent")

        audits_a = tenants.client.get("/api/v1/audit-logs", headers=tenants.headers_a)
        dashboard_a = tenants.client.get("/api/v1/dashboard/summary", headers=tenants.headers_a)
        compliance_a = tenants.client.get(
            "/api/v1/compliance/summary",
            headers=tenants.headers_a,
        )

        assert audits_a.json()["total"] == 1
        assert audits_a.json()["items"][0]["organization_id"] == tenants.organization_a_id
        assert dashboard_a.json()["total_agents"] == 1
        assert compliance_a.json()["total_agents"] == 1


def test_user_administration_is_tenant_scoped() -> None:
    with tenant_clients() as tenants:
        users_a = tenants.client.get("/api/v1/users", headers=tenants.headers_a)
        users_b = tenants.client.get("/api/v1/users", headers=tenants.headers_b)
        user_b_id = users_b.json()["items"][0]["id"]

        cross_tenant_get = tenants.client.get(
            f"/api/v1/users/{user_b_id}",
            headers=tenants.headers_a,
        )
        cross_tenant_update = tenants.client.patch(
            f"/api/v1/users/{user_b_id}",
            headers=tenants.headers_a,
            json={"role": "auditor"},
        )

        assert users_a.json()["total"] == 1
        assert users_b.json()["total"] == 1
        assert users_a.json()["items"][0]["id"] != user_b_id
        assert cross_tenant_get.status_code == 404
        assert cross_tenant_update.status_code == 404


def test_mcp_server_cannot_link_cross_tenant_or_soft_deleted_agent() -> None:
    with tenant_clients() as tenants:
        agent_b = create_agent(tenants.client, tenants.headers_b, "Organization B MCP Agent")
        deleted_agent = create_agent(tenants.client, tenants.headers_a, "Deleted MCP Agent")
        server_a = tenants.client.post(
            "/api/v1/mcp-servers",
            headers=tenants.headers_a,
            json={
                "name": "Organization A MCP",
                "server_url": "https://mcp.example.com/a",
            },
        ).json()
        tenants.client.delete(
            f"/api/v1/agents/{deleted_agent['id']}",
            headers=tenants.headers_a,
        )

        cross_tenant = tenants.client.post(
            "/api/v1/mcp-servers",
            headers=tenants.headers_a,
            json={
                "name": "Cross Tenant MCP",
                "server_url": "https://mcp.example.com/cross",
                "agent_id": agent_b["id"],
            },
        )
        soft_deleted = tenants.client.post(
            "/api/v1/mcp-servers",
            headers=tenants.headers_a,
            json={
                "name": "Deleted Agent MCP",
                "server_url": "https://mcp.example.com/deleted",
                "agent_id": deleted_agent["id"],
            },
        )
        cross_tenant_update = tenants.client.patch(
            f"/api/v1/mcp-servers/{server_a['id']}",
            headers=tenants.headers_a,
            json={"agent_id": agent_b["id"]},
        )

        assert cross_tenant.status_code == 422
        assert soft_deleted.status_code == 422
        assert cross_tenant_update.status_code == 422


def test_organization_admin_changes_membership_not_global_user() -> None:
    with tenant_clients() as tenants:
        with tenants.session_local() as db:
            organization_a = db.get(Organization, UUID(tenants.organization_a_id))
            member = User(
                email="member-a@example.com",
                full_name="Member A",
                password_hash=hash_password("StrongPassword123!"),
                role=UserRole.AGENT_OWNER,
            )
            db.add(member)
            db.flush()
            db.add(
                OrganizationMembership(
                    organization_id=UUID(tenants.organization_a_id),
                    user_id=member.id,
                    role=UserRole.AGENT_OWNER,
                )
            )
            db.commit()
            member_id = member.id
            assert organization_a is not None

        role_update = tenants.client.patch(
            f"/api/v1/users/{member_id}",
            headers=tenants.headers_a,
            json={"role": "auditor"},
        )
        deactivation = tenants.client.post(
            f"/api/v1/users/{member_id}/deactivate",
            headers=tenants.headers_a,
        )

        assert role_update.status_code == 200
        assert role_update.json()["role"] == "auditor"
        assert deactivation.status_code == 200
        assert deactivation.json()["is_active"] is False
        with tenants.session_local() as db:
            persisted_user = db.get(User, member_id)
            persisted_membership = db.scalar(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == UUID(tenants.organization_a_id),
                    OrganizationMembership.user_id == member_id,
                )
            )
            assert persisted_user is not None
            assert persisted_user.role == UserRole.AGENT_OWNER
            assert persisted_user.is_active is True
            assert persisted_membership is not None
            assert persisted_membership.role == UserRole.AUDITOR
            assert persisted_membership.is_active is False


def test_last_active_organization_admin_cannot_be_demoted_or_deactivated() -> None:
    with tenant_clients() as tenants:
        current_admin = tenants.client.get("/api/v1/users", headers=tenants.headers_a).json()[
            "items"
        ][0]

        demote = tenants.client.patch(
            f"/api/v1/users/{current_admin['id']}",
            headers=tenants.headers_a,
            json={"role": "operator"},
        )
        deactivate = tenants.client.post(
            f"/api/v1/users/{current_admin['id']}/deactivate",
            headers=tenants.headers_a,
        )

        assert demote.status_code == 409
        assert deactivate.status_code == 409


def test_auditor_incident_access_is_read_only() -> None:
    with tenant_clients() as tenants:
        agent = create_agent(tenants.client, tenants.headers_a, "Incident Agent")
        incident = tenants.client.post(
            "/api/v1/incidents",
            headers=tenants.headers_a,
            json={
                "agent_id": agent["id"],
                "title": "Review incident",
                "description": "Requires auditor review.",
                "severity": "high",
            },
        ).json()
        with tenants.session_local() as db:
            auditor = User(
                email="auditor-a@example.com",
                full_name="Auditor A",
                password_hash=hash_password("StrongPassword123!"),
                role=UserRole.AGENT_OWNER,
            )
            db.add(auditor)
            db.flush()
            db.add(
                OrganizationMembership(
                    organization_id=UUID(tenants.organization_a_id),
                    user_id=auditor.id,
                    role=UserRole.AUDITOR,
                )
            )
            db.commit()
            auditor_headers = {"Authorization": f"Bearer {create_access_token(auditor)}"}

        assert tenants.client.get("/api/v1/incidents", headers=auditor_headers).status_code == 200
        assert (
            tenants.client.get(
                f"/api/v1/incidents/{incident['id']}",
                headers=auditor_headers,
            ).status_code
            == 200
        )
        assert (
            tenants.client.post(
                "/api/v1/incidents",
                headers=auditor_headers,
                json={
                    "agent_id": agent["id"],
                    "title": "Forbidden incident",
                    "description": "Auditor cannot create.",
                    "severity": "low",
                },
            ).status_code
            == 403
        )
        assert (
            tenants.client.patch(
                f"/api/v1/incidents/{incident['id']}",
                headers=auditor_headers,
                json={"assigned_to": "auditor"},
            ).status_code
            == 403
        )
        assert (
            tenants.client.post(
                f"/api/v1/incidents/{incident['id']}/resolve",
                headers=auditor_headers,
                json={"resolution_notes": "Forbidden."},
            ).status_code
            == 403
        )
        assert (
            tenants.client.post(
                f"/api/v1/incidents/{incident['id']}/dismiss",
                headers=auditor_headers,
            ).status_code
            == 403
        )


def test_cross_tenant_resource_ids_are_safely_hidden() -> None:
    with tenant_clients() as tenants:
        agent_b = create_agent(tenants.client, tenants.headers_b, "Organization B Resources")
        tool_b = tenants.client.post(
            f"/api/v1/agents/{agent_b['id']}/tools",
            headers=tenants.headers_b,
            json={"name": "org_b_tool", "permission": "execute", "risk_level": "medium"},
        ).json()
        mcp_b = tenants.client.post(
            "/api/v1/mcp-servers",
            headers=tenants.headers_b,
            json={"name": "Organization B MCP", "server_url": "https://mcp.example.com/b"},
        ).json()
        approval_b = tenants.client.post(
            "/api/v1/approvals",
            headers=tenants.headers_b,
            json={
                "agent_id": agent_b["id"],
                "requested_action": "sensitive_action",
                "risk_level": "high",
            },
        ).json()
        execution_b = tenants.client.post(
            "/api/v1/executions",
            headers=tenants.headers_b,
            json={
                "agent_id": agent_b["id"],
                "action_name": "tenant_b_action",
                "risk_level": "low",
            },
        ).json()
        incident_b = tenants.client.post(
            "/api/v1/incidents",
            headers=tenants.headers_b,
            json={
                "agent_id": agent_b["id"],
                "execution_id": execution_b["id"],
                "title": "Organization B incident",
                "description": "Must remain private to Organization B.",
                "severity": "high",
            },
        ).json()

        responses = [
            tenants.client.patch(
                f"/api/v1/agents/{agent_b['id']}/tools/{tool_b['id']}",
                headers=tenants.headers_a,
                json={"description": "cross-tenant update"},
            ),
            tenants.client.delete(
                f"/api/v1/agents/{agent_b['id']}/tools/{tool_b['id']}",
                headers=tenants.headers_a,
            ),
            tenants.client.get(
                f"/api/v1/mcp-servers/{mcp_b['id']}",
                headers=tenants.headers_a,
            ),
            tenants.client.get(
                f"/api/v1/executions/{execution_b['id']}",
                headers=tenants.headers_a,
            ),
            tenants.client.post(
                f"/api/v1/approvals/{approval_b['id']}/approve",
                headers=tenants.headers_a,
            ),
            tenants.client.get(
                f"/api/v1/incidents/{incident_b['id']}",
                headers=tenants.headers_a,
            ),
        ]

        assert all(response.status_code == 404 for response in responses)
        security_events = tenants.client.get(
            "/api/v1/audit-logs",
            headers=tenants.headers_a,
            params={"action": "security.cross_org_access_denied"},
        ).json()
        assert security_events["total"] >= 6
        assert all(
            event["organization_id"] == tenants.organization_a_id
            for event in security_events["items"]
        )
        assert all(
            tenants.organization_b_id not in str(event) for event in security_events["items"]
        )


def test_inactive_membership_is_denied() -> None:
    with tenant_clients() as tenants:
        inactive_headers = create_tenant_user(
            tenants,
            organization_id=tenants.organization_a_id,
            email="inactive-member@example.com",
            role=UserRole.ADMIN,
            is_active=False,
        )

        response = tenants.client.get("/api/v1/dashboard/summary", headers=inactive_headers)

        assert response.status_code == 403
        assert response.json()["detail"] == "Organization membership required."


def test_auditor_and_agent_owner_cannot_mutate_privileged_resources() -> None:
    with tenant_clients() as tenants:
        auditor_headers = create_tenant_user(
            tenants,
            organization_id=tenants.organization_a_id,
            email="viewer-auditor@example.com",
            role=UserRole.AUDITOR,
        )
        agent_owner_headers = create_tenant_user(
            tenants,
            organization_id=tenants.organization_a_id,
            email="member-agent-owner@example.com",
            role=UserRole.AGENT_OWNER,
        )

        auditor_agent_create = tenants.client.post(
            "/api/v1/agents",
            headers=auditor_headers,
            json={
                "name": "Forbidden Auditor Agent",
                "owner": "viewer-auditor@example.com",
                "department": "governance",
                "risk_level": "low",
            },
        )
        owner_policy_create = tenants.client.post(
            "/api/v1/policy-rules",
            headers=agent_owner_headers,
            json={
                "name": "Forbidden Owner Policy",
                "scope": "global",
                "risk_level": "high",
                "effect": "block",
            },
        )
        owner_users = tenants.client.get("/api/v1/users", headers=agent_owner_headers)
        owner_invites = tenants.client.get(
            "/api/v1/organization-invites",
            headers=agent_owner_headers,
        )

        assert auditor_agent_create.status_code == 403
        assert owner_policy_create.status_code == 403
        assert owner_users.status_code == 403
        assert owner_invites.status_code == 403


def test_admin_can_manage_resources_but_no_organization_delete_endpoint_exists() -> None:
    with tenant_clients() as tenants:
        created = create_agent(tenants.client, tenants.headers_a, "Admin Managed Agent")
        delete_organization = tenants.client.delete(
            f"/api/v1/organizations/{tenants.organization_a_id}",
            headers=tenants.headers_a,
        )

        assert created["name"] == "Admin Managed Agent"
        assert delete_organization.status_code in {404, 405}
