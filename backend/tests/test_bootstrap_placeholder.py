"""First-organization bootstrap over the historical Default Organization placeholder.

Migration 202606080004 creates a "Default Organization" on every database, including empty
ones, so a fresh install could never bootstrap. Bootstrap may now retire that placeholder,
but only when it is provably unused. PostgreSQL-specific concurrency coverage lives in
test_bootstrap_postgres.py.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from email_helpers import database_session
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.core.tenancy import (
    PLACEHOLDER_ORGANIZATION_NAME,
    PLACEHOLDER_ORGANIZATION_SLUG,
    OrganizationContextRequiredError,
    get_current_organization_id,
)
from app.models.agent import Agent, AgentRiskLevel
from app.models.audit_log import AuditAction, AuditLog
from app.models.email_outbox import EmailOutbox
from app.models.identity_token import EmailVerificationToken
from app.models.mcp_server import MCPServer
from app.models.organization import Organization, OrganizationMembership
from app.models.organization_invite import OrganizationInvite
from app.models.user import User, UserRole
from app.schemas.organization import OrganizationBootstrapRequest
from app.services import identity as identity_service
from app.services import organizations as organization_service
from app.services.email import ConsoleEmailBackend


@pytest.fixture()
def client(fresh_install_client: TestClient) -> TestClient:
    """These tests create the first organization themselves (bootstrap), so they start from a
    fresh install with no organization and no membership."""
    return fresh_install_client


JsonResponse = dict[str, Any]
PAYLOAD = {
    "organization_name": "Fresh Install Bank",
    "admin_full_name": "Fresh Admin",
    "admin_email": "fresh-admin@example.com",
    "admin_password": "FreshAdminPassword123!",
}


def create_placeholder(client: TestClient) -> UUID:
    """Reproduce what migration 202606080004 leaves on an empty database."""
    with database_session(client) as db:
        placeholder = Organization(
            name=PLACEHOLDER_ORGANIZATION_NAME, slug=PLACEHOLDER_ORGANIZATION_SLUG
        )
        db.add(placeholder)
        db.commit()
        return placeholder.id


def bootstrap(client: TestClient, **overrides: str) -> Any:
    return client.post("/api/v1/organizations/bootstrap", json={**PAYLOAD, **overrides})


def organizations(db: Session) -> list[Organization]:
    return list(db.scalars(select(Organization).order_by(Organization.created_at)).all())


def owner_user(db: Session) -> User:
    user = User(
        email=f"owner-{uuid4().hex[:8]}@example.com",
        full_name="Placeholder Owner",
        password_hash=hash_password("OwnerPassword123!"),
        role=UserRole.ADMIN,
    )
    db.add(user)
    db.flush()
    return user


def add_active_membership(db: Session, organization_id: UUID) -> None:
    db.add(
        OrganizationMembership(
            organization_id=organization_id, user_id=owner_user(db).id, role=UserRole.ADMIN
        )
    )


def add_inactive_membership(db: Session, organization_id: UUID) -> None:
    db.add(
        OrganizationMembership(
            organization_id=organization_id,
            user_id=owner_user(db).id,
            role=UserRole.AUDITOR,
            is_active=False,
        )
    )


def add_invite(db: Session, organization_id: UUID) -> None:
    db.add(
        OrganizationInvite(
            organization_id=organization_id,
            email="pending@example.com",
            role=UserRole.AUDITOR,
            token_hash="a" * 64,
            invited_by_user_id=owner_user(db).id,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
    )


def add_agent(db: Session, organization_id: UUID) -> None:
    db.add(
        Agent(
            organization_id=organization_id,
            name="Legacy Agent",
            owner="owner@example.com",
            department="Ops",
            risk_level=AgentRiskLevel.LOW,
        )
    )


def add_mcp_server(db: Session, organization_id: UUID) -> None:
    db.add(
        MCPServer(
            organization_id=organization_id,
            name="Legacy MCP",
            server_url="http://127.0.0.1:9/mcp",
        )
    )


def add_audit_reference(db: Session, organization_id: UUID) -> None:
    db.add(
        AuditLog(
            organization_id=organization_id,
            actor="system",
            action=AuditAction.AGENT_CREATED,
            entity_type="agent",
            entity_id=uuid4(),
        )
    )


# --- Pristine placeholder -----------------------------------------------------------------------


def test_pristine_placeholder_allows_bootstrap_and_is_soft_deleted(
    unauthenticated_client: TestClient,
) -> None:
    placeholder_id = create_placeholder(unauthenticated_client)

    response = bootstrap(unauthenticated_client)

    assert response.status_code == 201, response.text
    created_id = UUID(response.json()["user"]["organization_membership"]["organization"]["id"])
    assert created_id != placeholder_id
    with database_session(unauthenticated_client) as db:
        orgs = {org.id: org for org in organizations(db)}
        assert orgs[placeholder_id].deleted_at is not None
        assert orgs[placeholder_id].slug == PLACEHOLDER_ORGANIZATION_SLUG
        assert [org.id for org in orgs.values() if org.deleted_at is None] == [created_id]
        placeholders = db.scalar(
            select(func.count())
            .select_from(Organization)
            .where(Organization.slug == PLACEHOLDER_ORGANIZATION_SLUG)
        )
        assert placeholders == 1
        created_audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == AuditAction.ORGANIZATION_CREATED,
                AuditLog.entity_id == created_id,
            )
        )
        assert created_audit is not None
        assert created_audit.event_metadata == {
            "retired_placeholder_organization_id": str(placeholder_id)
        }
        # Identity atomicity is unchanged: one verification token and one queued email.
        assert db.scalar(select(func.count()).select_from(EmailVerificationToken)) == 1
        assert db.scalar(select(func.count()).select_from(EmailOutbox)) == 1


def test_bootstrap_without_any_organization_is_unchanged(
    unauthenticated_client: TestClient,
) -> None:
    response = bootstrap(unauthenticated_client)

    assert response.status_code == 201
    with database_session(unauthenticated_client) as db:
        assert len(organizations(db)) == 1
        created = db.scalar(
            select(AuditLog).where(AuditLog.action == AuditAction.ORGANIZATION_CREATED)
        )
        assert created is not None
        assert created.event_metadata is None


# --- Placeholders with any history are real tenants ---------------------------------------------


@pytest.mark.parametrize(
    "attach",
    [
        add_active_membership,
        add_inactive_membership,
        add_invite,
        add_agent,
        add_mcp_server,
        add_audit_reference,
    ],
    ids=["active-membership", "inactive-membership", "invite", "agent", "mcp-server", "audit"],
)
def test_placeholder_with_any_owned_data_blocks_bootstrap(
    unauthenticated_client: TestClient,
    attach: Callable[[Session, UUID], None],
) -> None:
    placeholder_id = create_placeholder(unauthenticated_client)
    with database_session(unauthenticated_client) as db:
        attach(db, placeholder_id)
        db.commit()

    response = bootstrap(unauthenticated_client)

    assert response.status_code == 409
    with database_session(unauthenticated_client) as db:
        orgs = organizations(db)
        assert [org.id for org in orgs] == [placeholder_id]
        assert orgs[0].deleted_at is None
        assert db.scalar(select(User).where(User.email == PAYLOAD["admin_email"])) is None


@pytest.mark.parametrize(
    ("name", "slug"),
    [("Acme Bank", PLACEHOLDER_ORGANIZATION_SLUG), (PLACEHOLDER_ORGANIZATION_NAME, "acme-bank")],
)
def test_partial_placeholder_identity_is_not_enough(
    unauthenticated_client: TestClient,
    name: str,
    slug: str,
) -> None:
    with database_session(unauthenticated_client) as db:
        db.add(Organization(name=name, slug=slug))
        db.commit()

    assert bootstrap(unauthenticated_client).status_code == 409


def test_real_organization_blocks_bootstrap(unauthenticated_client: TestClient) -> None:
    with database_session(unauthenticated_client) as db:
        db.add(Organization(name="Acme Bank", slug="acme-bank"))
        db.commit()

    response = bootstrap(unauthenticated_client)

    assert response.status_code == 409
    assert response.json() == {"detail": "An active organization already exists."}


def test_placeholder_plus_second_organization_blocks_bootstrap(
    unauthenticated_client: TestClient,
) -> None:
    create_placeholder(unauthenticated_client)
    with database_session(unauthenticated_client) as db:
        db.add(Organization(name="Acme Bank", slug="acme-bank"))
        db.commit()

    assert bootstrap(unauthenticated_client).status_code == 409


def test_second_bootstrap_after_placeholder_retirement_is_rejected(
    unauthenticated_client: TestClient,
) -> None:
    create_placeholder(unauthenticated_client)
    assert bootstrap(unauthenticated_client).status_code == 201

    second = bootstrap(
        unauthenticated_client,
        organization_name="Second Bank",
        admin_email="second-admin@example.com",
    )

    assert second.status_code == 409


# --- Retired placeholder is never reused or recreated -------------------------------------------


def test_retired_placeholder_is_never_resolved_or_recreated(
    unauthenticated_client: TestClient,
) -> None:
    placeholder_id = create_placeholder(unauthenticated_client)
    created = bootstrap(unauthenticated_client).json()
    created_id = UUID(created["user"]["organization_membership"]["organization"]["id"])

    with database_session(unauthenticated_client) as db:
        assert get_current_organization_id(db) == created_id
    with database_session(unauthenticated_client) as db:
        # Even with no active organization left, the retired placeholder must not come back.
        real = db.get(Organization, created_id)
        assert real is not None
        real.deleted_at = datetime.now(UTC)
        db.commit()
    with database_session(unauthenticated_client) as db:
        with pytest.raises(OrganizationContextRequiredError):
            get_current_organization_id(db)
        db.rollback()
        rows = organizations(db)
        assert {org.id for org in rows} == {placeholder_id, created_id}


def test_legacy_registration_never_joins_a_retired_placeholder(
    unauthenticated_client: TestClient,
) -> None:
    placeholder_id = create_placeholder(unauthenticated_client)
    assert bootstrap(unauthenticated_client).status_code == 201

    registered = unauthenticated_client.post(
        "/api/v1/auth/register",
        json={
            "email": "late-legacy@example.com",
            "full_name": "Late Legacy",
            "password": "LateLegacyPassword123!",
        },
    )

    assert registered.status_code == 201
    with database_session(unauthenticated_client) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(OrganizationMembership)
                .where(OrganizationMembership.organization_id == placeholder_id)
            )
            == 0
        )


# --- Failure atomicity ---------------------------------------------------------------------------


def test_failed_bootstrap_rolls_back_retirement_tokens_and_outbox(
    unauthenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    placeholder_id = create_placeholder(unauthenticated_client)
    original = identity_service.queue_email_verification

    def queue_then_fail(db: Session, user: User) -> EmailVerificationToken:
        original(db, user)  # token + outbox row are pending in the transaction...
        raise RuntimeError("simulated failure after queuing the verification email")

    monkeypatch.setattr(identity_service, "queue_email_verification", queue_then_fail)
    with database_session(unauthenticated_client) as db:
        with pytest.raises(RuntimeError):
            organization_service.bootstrap_organization(
                db,
                OrganizationBootstrapRequest(**cast(dict[str, Any], PAYLOAD)),
                ConsoleEmailBackend(),
            )

    with database_session(unauthenticated_client) as db:
        orgs = organizations(db)
        assert [org.id for org in orgs] == [placeholder_id]
        assert orgs[0].deleted_at is None
        assert db.scalar(select(User).where(User.email == PAYLOAD["admin_email"])) is None
        assert db.scalar(select(func.count()).select_from(EmailVerificationToken)) == 0
        assert db.scalar(select(func.count()).select_from(EmailOutbox)) == 0
        assert db.scalar(select(func.count()).select_from(OrganizationMembership)) == 0

    monkeypatch.setattr(identity_service, "queue_email_verification", original)
    assert bootstrap(unauthenticated_client).status_code == 201


def test_reference_scan_covers_every_organization_foreign_key() -> None:
    from app.db.base import Base

    referencing = {
        f"{table.name}.{column.name}"
        for table in Base.metadata.sorted_tables
        for column in table.columns
        if any(fk.column.table.name == "organizations" for fk in column.foreign_keys)
    }
    required = {
        "organization_memberships.organization_id",
        "organization_invites.organization_id",
        "agents.organization_id",
        "agent_tools.organization_id",
        "mcp_servers.organization_id",
        "policy_rules.organization_id",
        "approvals.organization_id",
        "executions.organization_id",
        "incidents.organization_id",
        "audit_logs.organization_id",
        "email_outbox.organization_id",
        "mcp_gateway_tokens.organization_id",
        "mcp_gateway_call_records.organization_id",
        "governance_alerts.organization_id",
        "ai_risk_register.organization_id",
        "compliance_controls.organization_id",
        "risk_snapshots.organization_id",
    }
    assert required <= referencing
