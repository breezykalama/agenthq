from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.security import get_current_organization_context, hash_password
from app.db.base import Base
from app.models.organization import Organization, OrganizationMembership
from app.models.user import User, UserRole
from app.repositories import organizations as organization_repository

JsonResponse = dict[str, Any]


def bootstrap(client: TestClient) -> JsonResponse:
    response = client.post(
        "/api/v1/organizations/bootstrap",
        json={
            "organization_name": "Equity Bank",
            "admin_full_name": "Equity Admin",
            "admin_email": "equity-admin@example.com",
            "admin_password": "StrongPassword123!",
        },
    )
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def test_bootstrap_creates_organization_admin_membership_and_token(
    client: TestClient,
    unauthenticated_client: TestClient,
) -> None:
    result = bootstrap(unauthenticated_client)

    assert result["access_token"]
    assert result["token_type"] == "bearer"
    assert result["user"]["email"] == "equity-admin@example.com"
    assert result["user"]["role"] == "admin"
    membership = result["user"]["organization_membership"]
    assert membership["role"] == "admin"
    assert membership["organization"]["name"] == "Equity Bank"
    assert membership["organization"]["slug"] == "equity-bank"
    bootstrap_headers = {"Authorization": f"Bearer {result['access_token']}"}
    organization_audits = client.get(
        "/api/v1/audit-logs",
        headers=bootstrap_headers,
        params={"action": "organization.created"},
    ).json()
    membership_audits = client.get(
        "/api/v1/audit-logs",
        headers=bootstrap_headers,
        params={"action": "organization_membership.created"},
    ).json()
    assert organization_audits["total"] == 1
    assert membership_audits["total"] == 1


def test_bootstrap_token_me_includes_membership(unauthenticated_client: TestClient) -> None:
    result = bootstrap(unauthenticated_client)

    response = unauthenticated_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {result['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json()["organization_membership"]["organization"]["slug"] == "equity-bank"


def test_bootstrap_rejected_when_active_organization_exists(
    unauthenticated_client: TestClient,
) -> None:
    bootstrap(unauthenticated_client)

    response = unauthenticated_client.post(
        "/api/v1/organizations/bootstrap",
        json={
            "organization_name": "Second Organization",
            "admin_full_name": "Second Admin",
            "admin_email": "second-admin@example.com",
            "admin_password": "StrongPassword123!",
        },
    )

    assert response.status_code == 409


def test_legacy_registration_is_attached_to_default_organization(
    unauthenticated_client: TestClient,
) -> None:
    registration = unauthenticated_client.post(
        "/api/v1/auth/register",
        json={
            "email": "legacy-owner@example.com",
            "full_name": "Legacy Owner",
            "password": "StrongPassword123!",
        },
    )
    login = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={
            "email": "legacy-owner@example.com",
            "password": "StrongPassword123!",
        },
    )
    response = unauthenticated_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )

    assert registration.status_code == 201
    assert response.status_code == 200
    assert response.json()["role"] == "agent_owner"
    assert (
        response.json()["organization_membership"]["organization"]["slug"]
        == "default-organization"
    )


def test_organization_slug_and_membership_uniqueness() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(
            email="constraints@example.com",
            full_name="Constraints User",
            password_hash=hash_password("StrongPassword123!"),
            role=UserRole.ADMIN,
        )
        organization = Organization(name="Constraints Org", slug="constraints-org")
        db.add_all([user, organization])
        db.commit()
        db.refresh(user)
        db.refresh(organization)
        db.add(
            OrganizationMembership(
                organization_id=organization.id,
                user_id=user.id,
                role=UserRole.ADMIN,
            )
        )
        db.commit()

        db.add(Organization(name="Duplicate Slug", slug="constraints-org"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

        db.add(
            OrganizationMembership(
                organization_id=organization.id,
                user_id=user.id,
                role=UserRole.AUDITOR,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    engine.dispose()


def test_current_organization_context_uses_single_active_membership() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(
            email="context@example.com",
            full_name="Context User",
            password_hash=hash_password("StrongPassword123!"),
            role=UserRole.AGENT_OWNER,
        )
        organization = Organization(name="Context Org", slug="context-org")
        db.add_all([user, organization])
        db.flush()
        db.add(
            OrganizationMembership(
                organization_id=organization.id,
                user_id=user.id,
                role=UserRole.AUDITOR,
            )
        )
        db.commit()

        context = get_current_organization_context(user, db)

        assert context.current_user.id == user.id
        assert context.current_organization is not None
        assert context.current_organization.id == organization.id
        assert context.current_membership is not None
        assert context.current_role == UserRole.AUDITOR
        assert len(organization_repository.list_active_memberships_for_user(db, user.id)) == 1
    engine.dispose()


def test_deleted_organization_is_excluded_from_normal_membership_queries() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(
            email="deleted-org@example.com",
            full_name="Deleted Org User",
            password_hash=hash_password("StrongPassword123!"),
            role=UserRole.AGENT_OWNER,
        )
        organization = Organization(
            name="Deleted Org",
            slug="deleted-org",
            deleted_at=datetime.now(UTC),
        )
        db.add_all([user, organization])
        db.flush()
        db.add(
            OrganizationMembership(
                organization_id=organization.id,
                user_id=user.id,
                role=UserRole.ADMIN,
            )
        )
        db.commit()

        assert organization_repository.get_organization_by_slug(db, organization.slug) is None
        assert organization_repository.list_active_memberships_for_user(db, user.id) == []
    engine.dispose()
