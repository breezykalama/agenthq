from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.organization import Organization, OrganizationMembership
from app.models.user import User, UserRole


def count_active_organizations(db: Session) -> int:
    statement = (
        select(func.count())
        .select_from(Organization)
        .where(Organization.deleted_at.is_(None))
    )
    return db.scalar(statement) or 0


def get_organization_by_slug(db: Session, slug: str) -> Organization | None:
    return db.scalar(
        select(Organization).where(
            Organization.slug == slug,
            Organization.deleted_at.is_(None),
        )
    )


def get_organization_by_id(db: Session, organization_id: UUID) -> Organization | None:
    return db.scalar(
        select(Organization).where(
            Organization.id == organization_id,
            Organization.deleted_at.is_(None),
        )
    )


def organization_slug_exists(db: Session, slug: str) -> bool:
    statement = select(func.count()).select_from(Organization).where(Organization.slug == slug)
    return (db.scalar(statement) or 0) > 0


def create_organization_pending(db: Session, organization: Organization) -> Organization:
    db.add(organization)
    db.flush()
    return organization


def create_membership_pending(
    db: Session,
    membership: OrganizationMembership,
) -> OrganizationMembership:
    db.add(membership)
    db.flush()
    return membership


def get_active_membership(
    db: Session,
    organization_id: UUID,
    user_id: UUID,
) -> OrganizationMembership | None:
    return db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.is_active.is_(True),
        )
    )


def get_membership(
    db: Session,
    organization_id: UUID,
    user_id: UUID,
) -> OrganizationMembership | None:
    return db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user_id,
        )
    )


def lock_active_admin_memberships(db: Session, organization_id: UUID) -> int:
    statement = (
        select(OrganizationMembership.id)
        .where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.role == UserRole.ADMIN,
            OrganizationMembership.is_active.is_(True),
        )
        .with_for_update()
    )
    return len(db.scalars(statement).all())


def update_membership_pending(
    db: Session,
    membership: OrganizationMembership,
    values: dict[str, object],
) -> OrganizationMembership:
    for field, value in values.items():
        setattr(membership, field, value)
    db.add(membership)
    db.flush()
    return membership


def list_active_memberships_for_user(
    db: Session,
    user_id: UUID,
) -> list[tuple[OrganizationMembership, Organization]]:
    statement = (
        select(OrganizationMembership, Organization)
        .join(Organization, Organization.id == OrganizationMembership.organization_id)
        .where(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.is_active.is_(True),
            Organization.deleted_at.is_(None),
        )
    )
    return list(db.execute(statement).tuples().all())


def list_active_membership_users(
    db: Session,
    organization_id: UUID,
    *,
    limit: int,
    offset: int,
) -> tuple[list[tuple[User, OrganizationMembership]], int]:
    filters = [
        OrganizationMembership.organization_id == organization_id,
        OrganizationMembership.is_active.is_(True),
    ]
    statement = (
        select(User, OrganizationMembership)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .where(*filters)
        .order_by(User.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    count_statement = (
        select(func.count())
        .select_from(OrganizationMembership)
        .where(*filters)
    )
    return list(db.execute(statement).tuples().all()), db.scalar(count_statement) or 0


def get_active_membership_user(
    db: Session,
    organization_id: UUID,
    user_id: UUID,
) -> User | None:
    return db.scalar(
        select(User)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .where(
            User.id == user_id,
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.is_active.is_(True),
        )
    )
