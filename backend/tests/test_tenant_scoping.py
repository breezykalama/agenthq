from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.models.agent import Agent
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
    with TestClient(app) as client:
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
            persisted = db.scalar(
                select(Agent).where(Agent.id == UUID(injected.json()["id"]))
            )
            assert persisted is not None
            assert str(persisted.organization_id) == tenants.organization_a_id


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
