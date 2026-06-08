from fastapi.testclient import TestClient

from app.api.pagination import DEFAULT_LIMIT, MAX_LIMIT, get_pagination
from app.db.base import Base


def create_agent(client: TestClient, name: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/agents",
        json={
            "name": name,
            "owner": "admin@agenthq.local",
            "department": "Governance",
            "risk_level": "low",
            "status": "draft",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_pagination_defaults_and_clamps_limit() -> None:
    assert get_pagination().limit == DEFAULT_LIMIT
    assert get_pagination(limit=MAX_LIMIT + 1).limit == MAX_LIMIT


def test_agent_list_paginates_and_preserves_total(client: TestClient) -> None:
    for index in range(3):
        create_agent(client, f"Pagination Agent {index}")

    first_page = client.get("/api/v1/agents?limit=1&offset=0")
    second_page = client.get("/api/v1/agents?limit=1&offset=1")

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    assert first_page.json()["total"] == 3
    assert second_page.json()["total"] == 3
    assert len(first_page.json()["items"]) == 1
    assert len(second_page.json()["items"]) == 1
    assert first_page.json()["items"][0]["id"] != second_page.json()["items"][0]["id"]


def test_list_endpoints_accept_pagination(client: TestClient) -> None:
    agent = create_agent(client, "Pagination Coverage Agent")
    registered_user = client.post(
        "/api/v1/auth/register",
        json={
            "email": "pagination@agenthq.example",
            "full_name": "Pagination User",
            "password": "PaginationPassword123!",
        },
    )
    assert registered_user.status_code == 201
    endpoints = [
        "/api/v1/agents",
        f"/api/v1/agents/{agent['id']}/tools",
        "/api/v1/mcp-servers",
        "/api/v1/policy-rules",
        "/api/v1/approvals",
        "/api/v1/executions",
        "/api/v1/incidents",
        "/api/v1/audit-logs",
        "/api/v1/users",
        "/api/v1/compliance/incidents",
    ]

    for endpoint in endpoints:
        response = client.get(f"{endpoint}?limit=1&offset=0")
        assert response.status_code == 200, endpoint
        assert len(response.json()["items"]) <= 1


def test_limit_below_one_is_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/agents?limit=0")

    assert response.status_code == 422


def test_negative_offset_is_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/agents?offset=-1")

    assert response.status_code == 422


def test_first_wave_indexes_are_declared() -> None:
    expected_indexes = {
        "audit_logs": {
            "ix_audit_logs_created_at",
            "ix_audit_logs_entity_type_entity_id",
            "ix_audit_logs_action",
            "ix_audit_logs_actor",
        },
        "executions": {
            "ix_executions_created_at",
            "ix_executions_agent_id_created_at",
            "ix_executions_status_created_at",
        },
        "incidents": {
            "ix_incidents_created_at",
            "ix_incidents_agent_id_created_at",
            "ix_incidents_status_created_at",
        },
        "approvals": {
            "ix_approvals_agent_id_requested_at",
            "ix_approvals_status_requested_at",
        },
        "agent_tools": {"ix_agent_tools_agent_id_created_at"},
        "policy_rules": {"ix_policy_rules_scope_agent_id_tool_id_priority"},
        "mcp_servers": {"ix_mcp_servers_status", "ix_mcp_servers_agent_id"},
    }

    for table_name, expected_names in expected_indexes.items():
        actual_names = {index.name for index in Base.metadata.tables[table_name].indexes}
        assert expected_names <= actual_names
