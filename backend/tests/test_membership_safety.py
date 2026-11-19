"""v0.8.2 phase 0: accepting an invite must never leave a user with two active memberships.

The organization-context resolver only works for exactly one active membership, so a second one
would lock the user out of both organizations. Until organization selection exists, acceptance
by a user who is an active member elsewhere is rejected with 409 and the invite stays pending.
Concurrency is covered on PostgreSQL in test_membership_safety_postgres.py.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
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
from app.models.organization import Organization, OrganizationMembership
from app.models.organization_invite import OrganizationInvite, OrganizationInviteStatus
from app.models.user import User, UserRole

PASSWORD = "StrongPassword123!"
MULTIPLE_ORGANIZATIONS_DETAIL = "Multiple organizations are not yet supported."


@dataclass(frozen=True)
class World:
    client: TestClient
    session_local: sessionmaker[Session]
    organization_a: UUID
    organization_b: UUID
    deleted_organization: UUID
    admin_a: UUID
    operator_a: UUID
    loner: UUID
    headers_admin_a: dict[str, str]
    headers_admin_b: dict[str, str]
    headers_operator_a: dict[str, str]


def _user(email: str, role: UserRole) -> User:
    return User(email=email, full_name=email, password_hash=hash_password(PASSWORD), role=role)


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
        organization_a = Organization(name="Organization A", slug="organization-a")
        organization_b = Organization(name="Organization B", slug="organization-b")
        deleted = Organization(name="Deleted Org", slug="deleted-org", deleted_at=datetime.now(UTC))
        admin_a = _user("admin-a@example.com", UserRole.ADMIN)
        operator_a = _user("operator-a@example.com", UserRole.AGENT_OWNER)
        admin_b = _user("admin-b@example.com", UserRole.ADMIN)
        loner = _user("loner@example.com", UserRole.AGENT_OWNER)
        db.add_all([organization_a, organization_b, deleted, admin_a, operator_a, admin_b, loner])
        db.flush()
        db.add_all(
            [
                OrganizationMembership(
                    organization_id=organization_a.id, user_id=admin_a.id, role=UserRole.ADMIN
                ),
                OrganizationMembership(
                    organization_id=organization_a.id,
                    user_id=operator_a.id,
                    role=UserRole.OPERATOR,
                ),
                OrganizationMembership(
                    organization_id=organization_b.id, user_id=admin_b.id, role=UserRole.ADMIN
                ),
            ]
        )
        db.commit()
        ids = (organization_a.id, organization_b.id, deleted.id, admin_a.id, operator_a.id)
        loner_id = loner.id
        tokens = [create_access_token(user) for user in (admin_a, admin_b, operator_a)]

    def override_get_db() -> Iterator[Session]:
        with session_local() as db:
            yield db

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    with (
        patch("app.core.rate_limit.get_rate_limit_backend", return_value=rate_limiter),
        TestClient(app) as client,
    ):
        yield World(
            client=client,
            session_local=session_local,
            organization_a=ids[0],
            organization_b=ids[1],
            deleted_organization=ids[2],
            admin_a=ids[3],
            operator_a=ids[4],
            loner=loner_id,
            headers_admin_a={"Authorization": f"Bearer {tokens[0]}"},
            headers_admin_b={"Authorization": f"Bearer {tokens[1]}"},
            headers_operator_a={"Authorization": f"Bearer {tokens[2]}"},
        )
    rate_limiter.clear()
    engine.dispose()


def invite(w: World, email: str, *, role: str = "auditor") -> dict[str, Any]:
    response = w.client.post(
        "/api/v1/organization-invites",
        headers=w.headers_admin_b,
        json={"email": email, "role": role},
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def accept(w: World, token: str, *, password: str = PASSWORD) -> Any:
    return w.client.post(
        "/api/v1/organization-invites/accept",
        json={"token": token, "password": password},
    )


def membership_state(w: World, user_id: UUID) -> list[tuple[UUID, str, bool, datetime | None]]:
    with w.session_local() as db:
        rows = db.scalars(
            select(OrganizationMembership)
            .where(OrganizationMembership.user_id == user_id)
            .order_by(OrganizationMembership.organization_id)
        ).all()
        return [
            (row.organization_id, row.role.value, row.is_active, row.updated_at) for row in rows
        ]


def invite_state(w: World, invite_id: str) -> tuple[str, datetime | None, str, datetime | None]:
    with w.session_local() as db:
        row = db.get(OrganizationInvite, UUID(invite_id))
        assert row is not None
        return (row.status.value, row.accepted_at, row.token_hash, row.updated_at)


def user_state(w: World, user_id: UUID) -> tuple[Any, ...]:
    with w.session_local() as db:
        user = db.get(User, user_id)
        assert user is not None
        return (
            user.email,
            user.full_name,
            user.password_hash,
            user.role,
            user.is_active,
            user.email_verified,
            user.auth_version,
            user.updated_at,
        )


def test_active_member_elsewhere_is_rejected_and_nothing_changes() -> None:
    with world() as w:
        created = invite(w, "admin-a@example.com", role="admin")
        memberships_before = membership_state(w, w.admin_a)
        invite_before = invite_state(w, created["id"])
        user_before = user_state(w, w.admin_a)

        response = accept(w, created["token"])

        assert response.status_code == 409
        assert response.json() == {"detail": MULTIPLE_ORGANIZATIONS_DETAIL}
        assert "access_token" not in response.text
        # Organization A membership untouched, no Organization B membership created.
        assert membership_state(w, w.admin_a) == memberships_before
        assert [row[0] for row in memberships_before] == [w.organization_a]
        # Invite still pending and unconsumed; global identity untouched.
        assert invite_state(w, created["id"]) == invite_before
        assert invite_before[0] == OrganizationInviteStatus.PENDING.value
        assert invite_before[1] is None
        assert user_state(w, w.admin_a) == user_before


def test_sole_admin_keeps_access_to_their_organization_after_rejection() -> None:
    with world() as w:
        created = invite(w, "admin-a@example.com")
        assert accept(w, created["token"]).status_code == 409

        me = w.client.get("/api/v1/auth/me", headers=w.headers_admin_a)
        members = w.client.get("/api/v1/users", headers=w.headers_admin_a)

        assert me.status_code == 200
        membership = me.json()["organization_membership"]
        assert membership["organization"]["id"] == str(w.organization_a)
        assert membership["role"] == "admin"
        assert members.status_code == 200
        assert {item["email"] for item in members.json()["items"]} == {
            "admin-a@example.com",
            "operator-a@example.com",
        }


def test_rejected_invite_stays_reusable_once_the_other_membership_is_inactive() -> None:
    with world() as w:
        created = invite(w, "operator-a@example.com", role="operator")
        assert accept(w, created["token"]).status_code == 409

        deactivated = w.client.patch(
            f"/api/v1/users/{w.operator_a}",
            headers=w.headers_admin_a,
            json={"is_active": False},
        )
        assert deactivated.status_code == 200

        # Inactive membership elsewhere does not block (existing behavior) and the same token
        # that was rejected earlier is still valid.
        accepted = accept(w, created["token"])
        assert accepted.status_code == 200
        body = accepted.json()
        assert body["user"]["organization_membership"]["organization"]["id"] == str(
            w.organization_b
        )
        states = {row[0]: row[2] for row in membership_state(w, w.operator_a)}
        assert states == {w.organization_a: False, w.organization_b: True}
        assert invite_state(w, created["id"])[0] == OrganizationInviteStatus.ACCEPTED.value

        # Single-use protection still holds after the earlier rejection.
        replay = accept(w, created["token"])
        assert replay.status_code == 400
        assert replay.json()["detail"] == "Invite is invalid or expired."

        # The new token works in Organization B only.
        me = w.client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
        )
        assert me.json()["organization_membership"]["organization"]["id"] == str(w.organization_b)


def test_user_without_active_membership_can_accept() -> None:
    with world() as w:
        created = invite(w, "loner@example.com")

        response = accept(w, created["token"])

        assert response.status_code == 200
        assert [(row[0], row[1], row[2]) for row in membership_state(w, w.loner)] == [
            (w.organization_b, "auditor", True)
        ]


def test_new_user_acceptance_is_unchanged() -> None:
    with world() as w:
        created = invite(w, "brand-new@example.com")

        response = w.client.post(
            "/api/v1/organization-invites/accept",
            json={"token": created["token"], "password": PASSWORD, "full_name": "Brand New"},
        )

        assert response.status_code == 200
        assert response.json()["user"]["email"] == "brand-new@example.com"


def test_active_membership_in_deleted_organization_does_not_block() -> None:
    # The resolver ignores deleted organizations, so such a membership cannot cause a lockout.
    with world() as w:
        with w.session_local() as db:
            db.add(
                OrganizationMembership(
                    organization_id=w.deleted_organization, user_id=w.loner, role=UserRole.ADMIN
                )
            )
            db.commit()
        created = invite(w, "loner@example.com")

        assert accept(w, created["token"]).status_code == 200


def test_inactive_membership_in_same_organization_keeps_existing_409() -> None:
    # Existing behavior (unchanged by phase 0): the (organization, user) unique index rejects a
    # second row, the transaction rolls back, and the invite stays pending.
    with world() as w:
        with w.session_local() as db:
            db.add(
                OrganizationMembership(
                    organization_id=w.organization_b,
                    user_id=w.loner,
                    role=UserRole.AUDITOR,
                    is_active=False,
                )
            )
            db.commit()
        created = invite(w, "loner@example.com")

        response = accept(w, created["token"])

        assert response.status_code == 409
        assert response.json()["detail"] == "User is already a member of this organization."
        assert invite_state(w, created["id"])[0] == OrganizationInviteStatus.PENDING.value


def test_wrong_password_and_expiry_are_checked_before_the_guard() -> None:
    # A token holder without the account password learns nothing about other memberships.
    with world() as w:
        created = invite(w, "admin-a@example.com")
        wrong_password = accept(w, created["token"], password="NotThePassword123!")
        assert wrong_password.status_code == 400
        assert wrong_password.json()["detail"] == "Invite is invalid or expired."

        with w.session_local() as db:
            row = db.get(OrganizationInvite, UUID(created["id"]))
            assert row is not None
            row.expires_at = datetime(2020, 1, 1, tzinfo=UTC)
            db.commit()
        expired = accept(w, created["token"])
        assert expired.status_code == 400
        assert expired.json()["detail"] == "Invite is invalid or expired."
        assert [row[0] for row in membership_state(w, w.admin_a)] == [w.organization_a]


def test_existing_member_of_same_organization_keeps_existing_409() -> None:
    with world() as w:
        created = w.client.post(
            "/api/v1/organization-invites",
            headers=w.headers_admin_a,
            json={"email": "operator-a@example.com", "role": "auditor"},
        ).json()

        response = accept(w, created["token"])

        assert response.status_code == 409
        assert response.json()["detail"] == "User is already a member of this organization."
