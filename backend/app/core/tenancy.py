from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Organization

TENANT_SESSION_KEY = "organization_id"


class OrganizationContextRequiredError(Exception):
    pass


def set_current_organization_id(db: Session, organization_id: UUID) -> None:
    db.info[TENANT_SESSION_KEY] = organization_id


def get_current_organization_id(db: Session) -> UUID:
    organization_id = db.info.get(TENANT_SESSION_KEY)
    if isinstance(organization_id, UUID):
        return organization_id

    organizations = list(
        db.scalars(
            select(Organization.id).where(Organization.deleted_at.is_(None)).limit(2)
        ).all()
    )
    if len(organizations) == 1:
        set_current_organization_id(db, organizations[0])
        return organizations[0]
    if not organizations:
        organization = Organization(name="Default Organization", slug="default-organization")
        db.add(organization)
        db.flush()
        set_current_organization_id(db, organization.id)
        return organization.id
    raise OrganizationContextRequiredError


def get_optional_organization_id(db: Session) -> UUID | None:
    organization_id = db.info.get(TENANT_SESSION_KEY)
    return organization_id if isinstance(organization_id, UUID) else None
