from typing import Any, cast
from uuid import UUID

import pytest
from email_helpers import database_session
from fastapi.testclient import TestClient
from membership_helpers import enroll
from sqlalchemy import select

from app.models.audit_log import AuditAction, AuditLog

# These tests register accounts through the legacy endpoint, which is off by default.
pytestmark = pytest.mark.usefixtures("public_registration")


JsonResponse = dict[str, Any]


def register(client: TestClient, email: str = "owner@example.com") -> JsonResponse:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Agent Owner",
            "password": "StrongPassword123!",
        },
    )
    assert response.status_code == 201
    # Registration grants no organization access; the admin provisions the membership.
    enroll(client, response.json()["id"])
    return cast(JsonResponse, response.json())


def login(client: TestClient, email: str, password: str = "StrongPassword123!") -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return cast(str, response.json()["access_token"])


def test_register_hashes_password_and_defaults_to_agent_owner(
    unauthenticated_client: TestClient,
) -> None:
    user = register(unauthenticated_client)

    assert user["role"] == "agent_owner"
    assert "password" not in user
    assert "password_hash" not in user


def test_login_returns_jwt_and_me_returns_user(unauthenticated_client: TestClient) -> None:
    register(unauthenticated_client)
    token = login(unauthenticated_client, "owner@example.com")

    response = unauthenticated_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == "owner@example.com"


def test_invalid_password_rejected(unauthenticated_client: TestClient) -> None:
    register(unauthenticated_client)

    response = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "WrongPassword123!"},
    )

    assert response.status_code == 401


def test_invalid_jwt_rejected(unauthenticated_client: TestClient) -> None:
    response = unauthenticated_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == 401


def test_protected_endpoint_requires_authentication(unauthenticated_client: TestClient) -> None:
    assert unauthenticated_client.get("/api/v1/dashboard/summary").status_code == 401


def test_agent_owner_cannot_access_admin_endpoint(unauthenticated_client: TestClient) -> None:
    register(unauthenticated_client)
    token = login(unauthenticated_client, "owner@example.com")

    response = unauthenticated_client.get(
        "/api/v1/mcp-servers",
        headers={"Authorization": f"Bearer {token}"},
    )

    # Denied by the agent_owner role of an explicit membership, not by a missing membership.
    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient permissions."}


def test_admin_can_manage_users(client: TestClient, unauthenticated_client: TestClient) -> None:
    user = register(unauthenticated_client)

    response = client.patch(f"/api/v1/users/{user['id']}", json={"role": "auditor"})

    assert response.status_code == 200
    assert response.json()["role"] == "auditor"


def test_deactivated_membership_does_not_deactivate_global_user(
    client: TestClient,
    unauthenticated_client: TestClient,
) -> None:
    user = register(unauthenticated_client)
    token = login(unauthenticated_client, "owner@example.com")
    active = unauthenticated_client.get(
        "/api/v1/dashboard/summary", headers={"Authorization": f"Bearer {token}"}
    )
    deactivated = client.post(f"/api/v1/users/{user['id']}/deactivate")

    me_response = unauthenticated_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    dashboard_response = unauthenticated_client.get(
        "/api/v1/dashboard/summary",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert active.status_code == 200  # a real member before deactivation
    assert deactivated.status_code == 200
    assert me_response.status_code == 200
    assert me_response.json()["is_active"] is True
    assert dashboard_response.status_code == 403
    assert dashboard_response.json() == {"detail": "Organization membership required."}


def test_auditor_can_access_audit_logs_but_not_executions(
    client: TestClient,
    unauthenticated_client: TestClient,
) -> None:
    user = register(unauthenticated_client, "auditor@example.com")
    client.patch(f"/api/v1/users/{user['id']}", json={"role": "auditor"})
    token = login(unauthenticated_client, "auditor@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    assert unauthenticated_client.get("/api/v1/audit-logs", headers=headers).status_code == 200
    assert unauthenticated_client.get("/api/v1/executions", headers=headers).status_code == 403


def test_operator_can_access_executions_but_not_policy_rules(
    client: TestClient,
    unauthenticated_client: TestClient,
) -> None:
    user = register(unauthenticated_client, "operator@example.com")
    client.patch(f"/api/v1/users/{user['id']}", json={"role": "operator"})
    token = login(unauthenticated_client, "operator@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    assert unauthenticated_client.get("/api/v1/executions", headers=headers).status_code == 200
    assert unauthenticated_client.get("/api/v1/policy-rules", headers=headers).status_code == 403


def test_agent_owner_only_sees_and_manages_assigned_agents(
    client: TestClient,
    unauthenticated_client: TestClient,
) -> None:
    register(unauthenticated_client)
    token = login(unauthenticated_client, "owner@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    owned = unauthenticated_client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": "Owned Agent",
            "owner": "owner@example.com",
            "department": "operations",
            "risk_level": "medium",
        },
    )
    other = client.post(
        "/api/v1/agents",
        json={
            "name": "Other Agent",
            "owner": "another@example.com",
            "department": "operations",
            "risk_level": "medium",
        },
    )

    listing = unauthenticated_client.get("/api/v1/agents", headers=headers)

    assert owned.status_code == 201
    assert other.status_code == 201
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["id"] == owned.json()["id"]
    assert (
        unauthenticated_client.get(
            f"/api/v1/agents/{other.json()['id']}", headers=headers
        ).status_code
        == 403
    )


def test_user_actions_create_audit_logs(
    client: TestClient,
    unauthenticated_client: TestClient,
) -> None:
    user = register(unauthenticated_client)
    login(unauthenticated_client, "owner@example.com")
    client.patch(f"/api/v1/users/{user['id']}", json={"role": "operator"})
    client.post(f"/api/v1/users/{user['id']}/deactivate")

    response = client.get("/api/v1/audit-logs", params={"entity_id": user["id"]})

    assert response.status_code == 200
    # Registration belongs to no organization, so its user.created event is recorded without
    # one (it is not part of this organization's log); later actions are organization-scoped.
    assert {item["action"] for item in response.json()["items"]} == {
        "user.login",
        "user.updated",
        "user.deactivated",
    }
    with database_session(client) as db:
        created = db.scalars(
            select(AuditLog).where(
                AuditLog.action == AuditAction.USER_CREATED,
                AuditLog.entity_id == UUID(user["id"]),
            )
        ).all()
    assert [row.organization_id for row in created] == [None]


def test_dashboard_counts_total_and_active_users(
    client: TestClient,
    unauthenticated_client: TestClient,
) -> None:
    user = register(unauthenticated_client)
    client.post(f"/api/v1/users/{user['id']}/deactivate")

    response = client.get("/api/v1/dashboard/summary")

    assert response.status_code == 200
    assert response.json()["total_users"] == 1
    assert response.json()["active_users"] == 1
