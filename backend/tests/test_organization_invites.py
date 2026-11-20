from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

import pytest
from email_helpers import (
    capture_email,
    database_session,
    deliver_outbox,
    raw_token_from_message,
    verify_pending_admin,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models.audit_log import AuditLog
from app.models.email_outbox import EmailOutbox, EmailOutboxKind, EmailOutboxStatus
from app.models.organization import OrganizationMembership
from app.models.organization_invite import OrganizationInvite
from app.models.user import User
from app.services.email import EmailDeliveryError, OutboundEmail
from app.services.organization_invites import token_digest


@pytest.fixture()
def client(fresh_install_client: TestClient) -> TestClient:
    """These tests create the first organization themselves (bootstrap), so they start from a
    fresh install with no organization and no membership."""
    return fresh_install_client


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
    verify_pending_admin(client)
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
    assert invite["email_delivery"] == "queued"
    assert invite["invite_url"].startswith("http://localhost:5173/?auth=invite#token=")
    assert invite["invite_url"].endswith(invite["token"])
    assert invite["token"] != token_digest(invite["token"])
    assert "token_hash" not in invite
    assert "token" not in listing["items"][0]
    assert "token_hash" not in listing["items"][0]
    assert listing["items"][0]["organization_id"] == invite["organization_id"]


def test_invite_email_failure_keeps_invite_retries_and_is_audited(
    unauthenticated_client: TestClient,
) -> None:
    headers = admin_headers(unauthenticated_client)

    class FailingEmailBackend:
        enabled = True

        def send(self, message: OutboundEmail) -> bool:
            raise EmailDeliveryError("private SMTP detail")

    response = unauthenticated_client.post(
        "/api/v1/organization-invites",
        headers=headers,
        json={"email": "failed-delivery@example.com", "role": "auditor"},
    )
    deliver_outbox(unauthenticated_client, FailingEmailBackend())
    listing = unauthenticated_client.get("/api/v1/organization-invites", headers=headers)
    audits = unauthenticated_client.get(
        "/api/v1/audit-logs",
        headers=headers,
        params={"action": "organization_invite.email_failed"},
    )

    # The invite committed before any email was attempted; delivery failure is recorded and
    # the outbox retries it instead of reporting a misleading success.
    assert response.status_code == 201
    assert response.json()["email_delivery"] == "queued"
    assert listing.json()["total"] == 1
    assert audits.json()["total"] == 1
    assert "private SMTP detail" not in audits.text
    with database_session(unauthenticated_client) as db:
        row = db.scalar(
            select(EmailOutbox).where(EmailOutbox.kind == EmailOutboxKind.ORGANIZATION_INVITE)
        )
        assert row is not None
        assert row.status == EmailOutboxStatus.PENDING
        assert row.attempts == 1


def test_invite_email_link_is_sent_after_commit_and_accepts(
    unauthenticated_client: TestClient,
) -> None:
    headers = admin_headers(unauthenticated_client)
    backend = capture_email(unauthenticated_client)

    invite = create_invite(unauthenticated_client, headers, email="linked@example.com")
    assert backend.messages == []
    deliver_outbox(unauthenticated_client)

    assert len(backend.messages) == 1
    message = backend.messages[0]
    assert message.to == "linked@example.com"
    assert "Equity Bank" in message.text_body
    assert "expires in 7 days" in message.text_body
    raw_token = raw_token_from_message(message.text_body)
    assert raw_token == invite["token"]
    accepted = accept_invite(unauthenticated_client, raw_token, full_name=None)
    assert accepted["user"]["email"] == "linked@example.com"
    assert accepted["user"]["email_verified"] is True


def test_revoked_invite_email_is_not_sent(unauthenticated_client: TestClient) -> None:
    headers = admin_headers(unauthenticated_client)
    backend = capture_email(unauthenticated_client)
    invite = create_invite(unauthenticated_client, headers, email="revoked-early@example.com")

    revoked = unauthenticated_client.post(
        f"/api/v1/organization-invites/{invite['id']}/revoke", headers=headers
    )
    deliver_outbox(unauthenticated_client)

    assert revoked.status_code == 200
    assert backend.messages == []
    with database_session(unauthenticated_client) as db:
        row = db.scalar(
            select(EmailOutbox).where(EmailOutbox.kind == EmailOutboxKind.ORGANIZATION_INVITE)
        )
        assert row is not None
        assert row.status == EmailOutboxStatus.CANCELLED
        assert row.token_nonce is None


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


def _replay_state(client: TestClient, invite_id: str) -> tuple[int, int, int, tuple[object, ...]]:
    """Counts and invite-row state a replayed acceptance must leave untouched."""
    with database_session(client) as db:
        invite = db.get(OrganizationInvite, UUID(invite_id))
        assert invite is not None
        return (
            db.scalar(select(func.count()).select_from(AuditLog)) or 0,
            db.scalar(select(func.count()).select_from(OrganizationMembership)) or 0,
            db.scalar(select(func.count()).select_from(User)) or 0,
            (invite.status, invite.accepted_at, invite.updated_at),
        )


def _accepted_invite(client: TestClient, *, existing_user: bool) -> tuple[JsonResponse, str]:
    headers = admin_headers(client)
    password = "InvitePassword123!"
    if existing_user:
        password = "ExistingPassword123!"
        registered = client.post(
            "/api/v1/auth/register",
            json={"email": "existing@example.com", "full_name": "Existing", "password": password},
        )
        assert registered.status_code == 201
    invite = create_invite(
        client, headers, email="existing@example.com" if existing_user else "invitee@example.com"
    )
    accept_invite(client, cast(str, invite["token"]), password=password)
    return invite, password


@pytest.mark.parametrize("existing_user", [False, True], ids=["new-user", "existing-user"])
def test_replaying_an_accepted_invite_with_the_correct_password_changes_nothing(
    unauthenticated_client: TestClient, existing_user: bool
) -> None:
    invite, password = _accepted_invite(unauthenticated_client, existing_user=existing_user)
    before = _replay_state(unauthenticated_client, cast(str, invite["id"]))

    replay = unauthenticated_client.post(
        "/api/v1/organization-invites/accept",
        json={"token": invite["token"], "password": password},
    )

    assert replay.status_code == 400
    assert replay.json() == {"detail": "Invite is invalid or expired."}
    assert "access_token" not in replay.text
    # No audit record, membership, account or invite-state change: the token stays single-use.
    assert _replay_state(unauthenticated_client, cast(str, invite["id"])) == before


@pytest.mark.parametrize("existing_user", [False, True], ids=["new-user", "existing-user"])
def test_replaying_an_accepted_invite_discloses_nothing_about_the_password(
    unauthenticated_client: TestClient, existing_user: bool
) -> None:
    invite, password = _accepted_invite(unauthenticated_client, existing_user=existing_user)
    before = _replay_state(unauthenticated_client, cast(str, invite["id"]))

    correct = unauthenticated_client.post(
        "/api/v1/organization-invites/accept",
        json={"token": invite["token"], "password": password},
    )
    wrong = unauthenticated_client.post(
        "/api/v1/organization-invites/accept",
        json={"token": invite["token"], "password": "WrongPassword123!"},
    )

    # Byte-identical replies: a consumed token cannot be used to test the account's password,
    # to learn whether the account exists, or to learn that the invitation was accepted.
    assert wrong.status_code == correct.status_code == 400
    assert wrong.content == correct.content
    assert wrong.headers.get("content-type") == correct.headers.get("content-type")
    assert _replay_state(unauthenticated_client, cast(str, invite["id"])) == before
