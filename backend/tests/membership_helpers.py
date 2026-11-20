"""Explicit organization membership for tests: there is no implicit membership any more."""

from collections.abc import Callable, Iterator
from typing import cast
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.organization import Organization, OrganizationMembership
from app.models.user import User, UserRole

FIXTURE_ADMIN_EMAIL = "admin@agenthq.local"


def enroll(client: TestClient, user_id: str | UUID, role: UserRole = UserRole.AGENT_OWNER) -> None:
    """Make an existing account an active member of the fixture admin's organization, as an
    administrator provisioning a member would (the conftest ``client`` fixture)."""
    app = cast(FastAPI, client.app)
    override = cast(Callable[[], Iterator[Session]], app.dependency_overrides[get_db])
    db = next(override())
    try:
        admin_org = db.scalar(
            select(Organization.id)
            .join(OrganizationMembership, OrganizationMembership.organization_id == Organization.id)
            .join(User, User.id == OrganizationMembership.user_id)
            .where(User.email == FIXTURE_ADMIN_EMAIL, OrganizationMembership.is_active.is_(True))
        )
        assert admin_org is not None, "enroll() needs the conftest client fixture's organization"
        db.add(
            OrganizationMembership(organization_id=admin_org, user_id=UUID(str(user_id)), role=role)
        )
        db.commit()
    finally:
        db.close()
