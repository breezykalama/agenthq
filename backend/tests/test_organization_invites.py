from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi.testclient import TestClient

from app.services.organization_invites import token_digest

JsonResponse = dict[str, Any]


def bootstrap(
    client: TestClient,
    *,
    name: str = "Equity Bank",
    email: str = "admin@example.com",
) -> JsonResponse:
    response = client.post(
        "/api/v1/organizations/bootstrap",
        json={
            "organization_name": name,
            "admin_full_name": "Organization Admin",
            "admin_email": email,
            "admin_password": "StrongPassword123!",
        },
    )
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def admin_headers(client: TestClient) -> dict[str, str]:
    result = bootstrap(client)
    return {"Authorization": f"Bearer {result['access_token']}"}


def create_invite(
    client: TestClient,
    headers: dict[str, str],
    *,
    email: str = "invitee@example.com",
    role: str = "auditor",
    full_name: str | None = "Invitee User",
) -> JsonResponse:
    payload: dict[str, object] = {"email": email, "role": role}
    if full_name is not None:
        payload["full_name"] = full_name
    response = client.post("/api/v1/organization-invites", headers=headers, json=payload)
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def accept_invite(
    client: TestClient,
    token: str,
    *,
    full_name: str | None = None,
    password: str = "InvitePassword123!",
) -> JsonResponse:
    payload: dict[str, object] = {"token": token, "password": password}
    if full_name is not None:
        payload["full_name"] = full_name
    response = client.post("/api/v1/organization-invites/accept", json=payload)
    assert response.status_code == 200
    return cast(JsonResponse, response.json())


def test_admin_can_create_invite_and_raw_token_is_not_listed(
    unauthenticated_client: TestClient,
) -> None:
    headers = admin_headers(unauthenticated_client)

    invite = create_invite(unauthenticated_client, headers)
    listing = unauthenticated_client.get("/api/v1/organization-invites", headers=headers).json()

    assert invite["token"]
    assert invite["invite_url"].endswith(invite["token"])
    assert invite["token"] != token_digest(invite["token"])
    assert "token_hash" not in invite
    assert "token" not in listing["items"][0]
    assert "token_hash" not in listing["items"][0]
    assert listing["items"][0]["organization_id"] == invite["organization_id"]


def test_non_admin_cannot_create_invite(unauthenticated_client: TestClient) -> None:
    registration = unauthenticated_client.post(
        "/api/v1/auth/register",
        json={
            "email": "owner@example.com",
            "full_name": "Agent Owner",
            "password": "StrongPassword123!",
        },
    )
    login = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "StrongPassword123!"},
    )

    assert registration.status_code == 201
    response = unauthenticated_client.post(
        "/api/v1/organization-invites",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json={"email": "invitee@example.com", "role": "operator"},
    )
    assert response.status_code == 403


def test_invite_list_filters_by_status_and_email(unauthenticated_client: TestClient) -> None:
    headers = admin_headers(unauthenticated_client)
    create_invite(unauthenticated_client, headers, email="first@example.com")
    second = create_invite(unauthenticated_client, headers, email="second@example.com")
    unauthenticated_client.post(
        f"/api/v1/organization-invites/{second['id']}/revoke",
        headers=headers,
    )

    response = unauthenticated_client.get(
        "/api/v1/organization-invites",
        headers=headers,
        params={"status": "pending", "email": "first@example.com"},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["email"] == "first@example.com"


def test_revoke_pending_invite_and_audit(unauthenticated_client: TestClient) -> None:
    headers = admin_headers(unauthenticated_client)
    invite = create_invite(unauthenticated_client, headers)

    response = unauthenticated_client.post(
        f"/api/v1/organization-invites/{invite['id']}/revoke",
        headers=headers,
    )
    audits = unauthenticated_client.get(
        "/api/v1/audit-logs",
        headers=headers,
        params={"action": "organization_invite.revoked"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "revoked"
    assert audits.status_code == 200
    assert audits.json()["total"] == 1


def test_accept_invite_creates_user_membership_token_and_audits(
    unauthenticated_client: TestClient,
) -> None:
    headers = admin_headers(unauthenticated_client)
    invite = create_invite(unauthenticated_client, headers, role="operator")

    result = accept_invite(unauthenticated_client, cast(str, invite["token"]))
    me = unauthenticated_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {result['access_token']}"},
    )
    accepted_audits = unauthenticated_client.get(
        "/api/v1/audit-logs",
        headers=headers,
        params={"action": "organization_invite.accepted"},
    )
    created_audits = unauthenticated_client.get(
        "/api/v1/audit-logs",
        headers=headers,
        params={"action": "organization_invite.created"},
    )

    assert result["access_token"]
    assert result["user"]["email"] == "invitee@example.com"
    assert result["user"]["role"] == "agent_owner"
    assert result["user"]["organization_membership"]["role"] == "operator"
    assert me.json()["organization_membership"]["role"] == "operator"
    assert accepted_audits.json()["total"] == 1
    assert created_audits.json()["total"] == 1


def test_accept_invite_attaches_existing_user(unauthenticated_client: TestClient) -> None:
    headers = admin_headers(unauthenticated_client)
    registration = unauthenticated_client.post(
        "/api/v1/auth/register",
        json={
            "email": "existing@example.com",
            "full_name": "Existing User",
            "password": "ExistingPassword123!",
        },
    )
    invite = create_invite(unauthenticated_client, headers, email="existing@example.com")

    result = accept_invite(
        unauthenticated_client,
        cast(str, invite["token"]),
        password="ExistingPassword123!",
    )

    assert registration.status_code == 201
    assert result["user"]["id"] == registration.json()["id"]
    assert result["user"]["organization_membership"]["role"] == "auditor"


def test_revoked_and_accepted_invites_cannot_be_reused_or_revoked(
    unauthenticated_client: TestClient,
) -> None:
    headers = admin_headers(unauthenticated_client)
    revoked = create_invite(unauthenticated_client, headers, email="revoked@example.com")
    accepted = create_invite(unauthenticated_client, headers, email="accepted@example.com")
    unauthenticated_client.post(
        f"/api/v1/organization-invites/{revoked['id']}/revoke",
        headers=headers,
    )
    accept_invite(unauthenticated_client, cast(str, accepted["token"]))

    revoked_accept = unauthenticated_client.post(
        "/api/v1/organization-invites/accept",
        json={"token": revoked["token"], "password": "InvitePassword123!"},
    )
    accepted_revoke = unauthenticated_client.post(
        f"/api/v1/organization-invites/{accepted['id']}/revoke",
        headers=headers,
    )

    assert revoked_accept.status_code == 400
    assert accepted_revoke.status_code == 409


def test_duplicate_pending_invite_and_membership_rejected(
    unauthenticated_client: TestClient,
) -> None:
    headers = admin_headers(unauthenticated_client)
    invite = create_invite(unauthenticated_client, headers)
    duplicate_invite = unauthenticated_client.post(
        "/api/v1/organization-invites",
        headers=headers,
        json={"email": "invitee@example.com", "role": "auditor"},
    )
    accept_invite(unauthenticated_client, cast(str, invite["token"]))
    second_invite = create_invite(unauthenticated_client, headers, email="invitee@example.com")
    duplicate_membership = unauthenticated_client.post(
        "/api/v1/organization-invites/accept",
        json={"token": second_invite["token"], "password": "InvitePassword123!"},
    )

    assert duplicate_invite.status_code == 409
    assert duplicate_membership.status_code == 409


def test_expired_invite_rejected(
    unauthenticated_client: TestClient,
    monkeypatch: Any,
) -> None:
    headers = admin_headers(unauthenticated_client)
    invite = create_invite(unauthenticated_client, headers)
    future = datetime.now(UTC) + timedelta(days=8)

    class FutureDateTime:
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return future

    monkeypatch.setattr("app.services.organization_invites.datetime", FutureDateTime)
    response = unauthenticated_client.post(
        "/api/v1/organization-invites/accept",
        json={"token": invite["token"], "password": "InvitePassword123!"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invite is invalid or expired."
