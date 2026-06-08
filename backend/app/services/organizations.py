import re
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
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


class OrganizationAlreadyBootstrappedError(Exception):
    pass


class BootstrapAdminEmailExistsError(Exception):
    pass


@dataclass(frozen=True)
class MembershipContext:
    membership: OrganizationMembership
    organization: Organization


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


def user_read_with_membership(db: Session, user: User) -> UserRead:
    membership_context = get_single_membership_context(db, user)
    return UserRead(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
        organization_membership=(
            membership_read(
                membership_context.membership,
                membership_context.organization,
            )
            if membership_context is not None
            else None
        ),
    )


def get_single_membership_context(db: Session, user: User) -> MembershipContext | None:
    memberships = organization_repository.list_active_memberships_for_user(db, user.id)
    if len(memberships) != 1:
        return None
    membership, organization = memberships[0]
    return MembershipContext(membership=membership, organization=organization)


def bootstrap_organization(
    db: Session,
    request: OrganizationBootstrapRequest,
) -> BootstrapTokenResponse:
    if organization_repository.count_active_organizations(db) > 0:
        raise OrganizationAlreadyBootstrappedError
    email = request.admin_email.lower()
    if user_repository.get_user_by_email(db, email) is not None:
        raise BootstrapAdminEmailExistsError

    try:
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

    return BootstrapTokenResponse(
        access_token=create_access_token(user),
        user=user_read_with_membership(db, user),
    )


def available_slug(db: Session, name: str) -> str:
    base_slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "organization"
    slug = base_slug
    suffix = 2
    while organization_repository.organization_slug_exists(db, slug):
        slug = f"{base_slug}-{suffix}"
        suffix += 1
    return slug
