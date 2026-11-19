import logging
import re
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.models  # noqa: F401  (registers every organization-owned table in the metadata)
from app.core.audit_context import set_actor_audit_context
from app.core.config import get_settings
from app.core.security import create_access_token, hash_password, select_membership
from app.core.tenancy import (
    PLACEHOLDER_ORGANIZATION_NAME,
    PLACEHOLDER_ORGANIZATION_SLUG,
    lock_organization_bootstrap,
    set_current_organization_id,
)
from app.db.base import Base
from app.models.audit_log import AuditAction, JsonObject
from app.models.organization import Organization, OrganizationMembership
from app.models.user import User, UserRole
from app.repositories import organizations as organization_repository
from app.repositories import users as user_repository
from app.schemas.audit_log import AuditLogCreate
from app.schemas.organization import (
    OrganizationBootstrapRequest,
    OrganizationMembershipRead,
    OrganizationRead,
)
from app.schemas.user import BootstrapTokenResponse, UserRead
from app.services import audit_logs as audit_log_service
from app.services import email_outbox
from app.services import identity as identity_service
from app.services.email import EmailBackend, EmailDeliveryError, delivery_enabled

organization_logger = logging.getLogger("agenthq.organizations")


class OrganizationAlreadyBootstrappedError(Exception):
    pass


class BootstrapAdminEmailExistsError(Exception):
    pass


def serialize_organization(organization: Organization) -> JsonObject:
    return OrganizationRead.model_validate(organization).model_dump(mode="json")


def serialize_membership(
    membership: OrganizationMembership,
    organization: Organization,
) -> JsonObject:
    return membership_read(membership, organization).model_dump(mode="json")


def membership_read(
    membership: OrganizationMembership,
    organization: Organization,
) -> OrganizationMembershipRead:
    return OrganizationMembershipRead(
        id=membership.id,
        organization_id=membership.organization_id,
        user_id=membership.user_id,
        role=membership.role,
        is_active=membership.is_active,
        created_at=membership.created_at,
        updated_at=membership.updated_at,
        organization=OrganizationRead.model_validate(organization),
    )


def _active_memberships(
    db: Session, user: User
) -> list[tuple[OrganizationMembership, Organization]]:
    """The user's own active memberships in non-deleted organizations, oldest first."""
    memberships = organization_repository.list_active_memberships_for_user(db, user.id)
    memberships.sort(key=lambda pair: (pair[1].created_at, str(pair[1].id)))
    return memberships


def list_user_memberships(db: Session, user: User) -> list[OrganizationMembershipRead]:
    return [
        membership_read(membership, organization)
        for membership, organization in _active_memberships(db, user)
    ]


def user_read_with_membership(
    db: Session,
    user: User,
    *,
    selected_organization_id: UUID | None = None,
    explicit_selection: bool = False,
) -> UserRead:
    """The caller's identity with their own memberships and the selected one.

    With an explicit selection (a header, or the organization just joined or created) the
    singular field is that organization's membership, or null when the caller has no active
    membership there; an explicit selection of None (a malformed header) selects nothing.
    Without one it is the only membership, or null when there are several. The selection is
    resolved against the caller's memberships only, exactly like the request resolver.
    """
    memberships = _active_memberships(db, user)
    if explicit_selection or selected_organization_id is not None:
        selected = (
            select_membership(memberships, selected_organization_id)
            if selected_organization_id is not None
            else None
        )
    else:
        selected = select_membership(memberships, None)
    return UserRead(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        email_verified=user.email_verified,
        email_verified_at=user.email_verified_at,
        email_verification_required=user.email_verification_required,
        created_at=user.created_at,
        updated_at=user.updated_at,
        organization_membership=membership_read(*selected) if selected is not None else None,
        organization_memberships=[
            membership_read(membership, organization) for membership, organization in memberships
        ],
        selected_organization_id=selected[1].id if selected is not None else None,
    )


def organization_references(db: Session, organization_id: UUID) -> dict[str, int]:
    """Count rows in every table holding a foreign key to organizations.id.

    Derived from model metadata (kept in parity with the database by `alembic check`), so a
    newly added organization-owned table is covered without changing this function.
    """
    references: dict[str, int] = {}
    for table in Base.metadata.sorted_tables:
        if table.name == Organization.__tablename__:
            continue
        for column in table.columns:
            if not any(
                foreign_key.column.table.name == Organization.__tablename__
                for foreign_key in column.foreign_keys
            ):
                continue
            count = db.scalar(
                select(func.count()).select_from(table).where(column == organization_id)
            )
            if count:
                references[f"{table.name}.{column.name}"] = int(count)
    return references


def is_unused_placeholder(db: Session, organization: Organization) -> bool:
    """True only for the migration/runtime placeholder with no history whatsoever: its exact
    name and slug, still active, and referenced by no row in any organization-owned table
    (memberships of any status, invites, agents, MCP servers, policies, approvals,
    executions, audit logs, outbox rows, ...). Anything else is treated as a real tenant."""
    return (
        organization.deleted_at is None
        and organization.slug == PLACEHOLDER_ORGANIZATION_SLUG
        and organization.name == PLACEHOLDER_ORGANIZATION_NAME
        and not organization_references(db, organization.id)
    )


def _active_organizations(db: Session, *, for_update: bool) -> list[Organization]:
    statement = (
        select(Organization)
        .where(Organization.deleted_at.is_(None))
        .order_by(Organization.created_at)
        .limit(2)
    )
    if for_update:
        statement = statement.with_for_update()
    return list(db.scalars(statement).all())


def bootstrap_blocked(db: Session) -> bool:
    """Unlocked pre-check for the API. bootstrap_organization re-decides under the lock."""
    active = _active_organizations(db, for_update=False)
    return bool(active) and not (len(active) == 1 and is_unused_placeholder(db, active[0]))


def find_claimable_placeholder(db: Session) -> Organization | None:
    """Must run under lock_organization_bootstrap. Returns the placeholder to retire, None
    when no organization exists, and raises when any real organization exists.

    The placeholder row is locked FOR UPDATE before its references are counted: a concurrent
    transaction inserting a row that references it holds a conflicting FOR KEY SHARE lock, so
    such a row is either committed (and counted) or blocked until this bootstrap finishes.
    """
    active = _active_organizations(db, for_update=True)
    if not active:
        return None
    if len(active) == 1 and is_unused_placeholder(db, active[0]):
        return active[0]
    raise OrganizationAlreadyBootstrappedError


def bootstrap_organization(
    db: Session,
    request: OrganizationBootstrapRequest,
    email_backend: EmailBackend,
) -> BootstrapTokenResponse:
    try:
        # Serialize every first-organization decision across processes. The lock is released
        # by the commit or rollback below, never earlier.
        lock_organization_bootstrap(db)
        placeholder = find_claimable_placeholder(db)
        email = request.admin_email.lower()
        if user_repository.get_user_by_email(db, email) is not None:
            raise BootstrapAdminEmailExistsError
        can_deliver = delivery_enabled(email_backend)
        if not can_deliver and get_settings().is_production:
            # A production administrator must be able to verify; refuse before writing.
            raise EmailDeliveryError("Email delivery is required in production.")

        retired_placeholder_id: UUID | None = None
        if placeholder is not None:
            # Soft-delete only: the row is kept for history and can never be reused, because
            # tenancy.get_current_organization_id refuses to recreate a retired placeholder.
            placeholder.deleted_at = datetime.now(UTC)
            retired_placeholder_id = placeholder.id
            db.flush()

        organization = organization_repository.create_organization_pending(
            db,
            Organization(
                name=request.organization_name,
                slug=available_slug(db, request.organization_name),
            ),
        )
        user = user_repository.create_user_pending(
            db,
            User(
                email=email,
                full_name=request.admin_full_name,
                password_hash=hash_password(request.admin_password),
                role=UserRole.ADMIN,
                # Mandatory verification applies to administrators bootstrapped from v0.8.1 on,
                # whenever a delivery channel exists to complete it.
                email_verification_required=can_deliver,
            ),
        )
        membership = organization_repository.create_membership_pending(
            db,
            OrganizationMembership(
                organization_id=organization.id,
                user_id=user.id,
                role=UserRole.ADMIN,
            ),
        )
        set_current_organization_id(db, organization.id)
        set_actor_audit_context(db, user_id=user.id, role=membership.role)
        audit_log_service.create_critical_audit_log(
            db,
            AuditLogCreate(
                organization_id=organization.id,
                actor=user.email,
                action=AuditAction.USER_CREATED,
                entity_type="user",
                entity_id=user.id,
                after=UserRead.model_validate(user).model_dump(mode="json"),
            ),
        )
        audit_log_service.create_critical_audit_log(
            db,
            AuditLogCreate(
                organization_id=organization.id,
                actor=user.email,
                action=AuditAction.ORGANIZATION_CREATED,
                entity_type="organization",
                entity_id=organization.id,
                after=serialize_organization(organization),
                # Recorded here rather than as a new audit action: a new enum value would need
                # a migration and break the v0.8.1-compatible rollback build.
                metadata=(
                    {"retired_placeholder_organization_id": str(retired_placeholder_id)}
                    if retired_placeholder_id is not None
                    else None
                ),
            ),
        )
        audit_log_service.create_critical_audit_log(
            db,
            AuditLogCreate(
                organization_id=organization.id,
                actor=user.email,
                action=AuditAction.ORGANIZATION_MEMBERSHIP_CREATED,
                entity_type="organization_membership",
                entity_id=membership.id,
                after=serialize_membership(membership, organization),
            ),
        )
        if can_deliver:
            identity_service.queue_email_verification(db, user)
        db.commit()
        db.refresh(organization)
        db.refresh(user)
        db.refresh(membership)
    except IntegrityError as exc:
        db.rollback()
        raise OrganizationAlreadyBootstrappedError from exc
    except Exception:
        db.rollback()
        raise

    if retired_placeholder_id is not None:
        organization_logger.info(
            "organization_placeholder_retired placeholder_id=%s organization_id=%s",
            retired_placeholder_id,
            organization.id,
        )
    email_outbox.notify_worker()
    return BootstrapTokenResponse(
        access_token=create_access_token(user),
        user=user_read_with_membership(db, user, selected_organization_id=organization.id),
    )


def available_slug(db: Session, name: str) -> str:
    base_slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "organization"
    slug = base_slug
    suffix = 2
    while organization_repository.organization_slug_exists(db, slug):
        slug = f"{base_slug}-{suffix}"
        suffix += 1
    return slug
