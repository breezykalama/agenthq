from typing import Any, cast

from fastapi.testclient import TestClient

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

    assert response.status_code == 403


def test_admin_can_manage_users(client: TestClient, unauthenticated_client: TestClient) -> None:
    user = register(unauthenticated_client)

    response = client.patch(f"/api/v1/users/{user['id']}", json={"role": "auditor"})

    assert response.status_code == 200
    assert response.json()["role"] == "auditor"


def test_deactivated_user_token_is_rejected(
    client: TestClient,
    unauthenticated_client: TestClient,
) -> None:
    user = register(unauthenticated_client)
    token = login(unauthenticated_client, "owner@example.com")
    client.post(f"/api/v1/users/{user['id']}/deactivate")

    response = unauthenticated_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


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
    client.patch(f"/api/v1/users/{user['id']}", json={"full_name": "Updated Owner"})
    client.post(f"/api/v1/users/{user['id']}/deactivate")

    response = client.get("/api/v1/audit-logs", params={"entity_id": user["id"]})

    assert response.status_code == 200
    assert {item["action"] for item in response.json()["items"]} == {
        "user.created",
        "user.login",
        "user.updated",
        "user.deactivated",
    }


def test_dashboard_counts_total_and_active_users(
    client: TestClient,
    unauthenticated_client: TestClient,
) -> None:
    user = register(unauthenticated_client)
    client.post(f"/api/v1/users/{user['id']}/deactivate")

    response = client.get("/api/v1/dashboard/summary")

    assert response.status_code == 200
    assert response.json()["total_users"] == 2
    assert response.json()["active_users"] == 1
