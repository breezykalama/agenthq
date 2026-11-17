from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.organization import Organization

TENANT_SESSION_KEY = "organization_id"

# Identity of the single-tenant placeholder created by migration 202606080004 (and, on an
# empty database, by get_current_organization_id below). Name and slug alone never prove a
# placeholder is unused; see organizations.find_claimable_placeholder.
PLACEHOLDER_ORGANIZATION_NAME = "Default Organization"
PLACEHOLDER_ORGANIZATION_SLUG = "default-organization"

# Transaction-scoped PostgreSQL advisory lock key ("AGHQBOOT"). Every code path that creates
# the first organization, retires the placeholder, or attaches data to the placeholder takes
# this lock, so those decisions are serialized across all processes and instances.
ORGANIZATION_BOOTSTRAP_LOCK_KEY = 0x4147_4851_424F_4F54


class OrganizationContextRequiredError(Exception):
    pass


def lock_organization_bootstrap(db: Session) -> None:
    """Hold the bootstrap advisory lock until the current transaction commits or rolls back.

    SQLite (unit tests) has no advisory locks and only one writer, so this is a no-op there.
    """
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": ORGANIZATION_BOOTSTRAP_LOCK_KEY},
        )


def placeholder_retired(db: Session) -> bool:
    retired = db.scalar(
        select(Organization.id)
        .where(
            Organization.slug == PLACEHOLDER_ORGANIZATION_SLUG,
            Organization.deleted_at.is_not(None),
        )
        .limit(1)
    )
    return retired is not None


def set_current_organization_id(db: Session, organization_id: UUID) -> None:
    db.info[TENANT_SESSION_KEY] = organization_id


def _active_organization_ids(db: Session) -> list[UUID]:
    return list(
        db.scalars(
            select(Organization.id).where(Organization.deleted_at.is_(None)).limit(2)
        ).all()
    )


def get_current_organization_id(db: Session) -> UUID:
    organization_id = db.info.get(TENANT_SESSION_KEY)
    if isinstance(organization_id, UUID):
        return organization_id

    organizations = _active_organization_ids(db)
    if not organizations:
        # Legacy single-tenant fallback. Re-check under the bootstrap lock so this can never
        # race a concurrent organization bootstrap into creating a second tenant.
        lock_organization_bootstrap(db)
        organizations = _active_organization_ids(db)
        if not organizations:
            if placeholder_retired(db):
                # A real organization was bootstrapped over the placeholder. Never resurrect it.
                raise OrganizationContextRequiredError
            organization = Organization(
                name=PLACEHOLDER_ORGANIZATION_NAME,
                slug=PLACEHOLDER_ORGANIZATION_SLUG,
            )
            db.add(organization)
            db.flush()
            set_current_organization_id(db, organization.id)
            return organization.id
    if len(organizations) == 1:
        set_current_organization_id(db, organizations[0])
        return organizations[0]
    raise OrganizationContextRequiredError


def get_optional_organization_id(db: Session) -> UUID | None:
    organization_id = db.info.get(TENANT_SESSION_KEY)
    return organization_id if isinstance(organization_id, UUID) else None
