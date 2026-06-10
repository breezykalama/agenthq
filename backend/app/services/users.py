from uuid import UUID

from sqlalchemy.orm import Session

from app.core.audit_context import set_actor_audit_context
from app.core.security import hash_password
from app.core.tenancy import get_current_organization_id, set_current_organization_id
from app.models.audit_log import AuditAction, JsonObject
from app.models.organization import Organization, OrganizationMembership
from app.models.user import User, UserRole
from app.repositories import organizations as organization_repository
from app.repositories import users as user_repository
from app.schemas.audit_log import AuditLogCreate
from app.schemas.organization import OrganizationMembershipRead, OrganizationRead
from app.schemas.user import UserRead, UserRegister, UserUpdate
from app.services import audit_logs as audit_log_service


class UserNotFoundError(Exception):
    pass


class DuplicateUserEmailError(Exception):
    pass


class LastOrganizationAdminError(Exception):
    pass


class GlobalUserIdentityUpdateNotAllowedError(Exception):
    pass


def serialize_user(user: User) -> JsonObject:
    return UserRead.model_validate(user).model_dump(mode="json")


def organization_member_read(
    user: User,
    membership: OrganizationMembership,
    organization: Organization,
) -> UserRead:
    organization_read = OrganizationRead.model_validate(organization)
    return UserRead(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=membership.role,
        is_active=membership.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
        organization_membership=OrganizationMembershipRead(
            id=membership.id,
            organization_id=membership.organization_id,
            user_id=membership.user_id,
            role=membership.role,
            is_active=membership.is_active,
            created_at=membership.created_at,
            updated_at=membership.updated_at,
            organization=organization_read,
        ),
    )


def register_user(db: Session, registration: UserRegister) -> User:
    email = registration.email.lower()
    if user_repository.get_user_by_email(db, email) is not None:
        raise DuplicateUserEmailError
    role = UserRole.ADMIN if user_repository.count_users(db) == 0 else UserRole.AGENT_OWNER
    user = user_repository.create_user(
        db,
        User(
            email=email,
            full_name=registration.full_name,
            password_hash=hash_password(registration.password),
            role=role,
        ),
    )
    active_organization_count = organization_repository.count_active_organizations(db)
    if active_organization_count == 0:
        organization_id = get_current_organization_id(db)
    elif active_organization_count == 1:
        organization_id = get_current_organization_id(db)
        organization = organization_repository.get_organization_by_id(db, organization_id)
        if organization is None or organization.slug != "default-organization":
            organization_id = None
    else:
        organization_id = None
    if organization_id is not None:
        organization_repository.create_membership_pending(
            db,
            OrganizationMembership(
                organization_id=organization_id,
                user_id=user.id,
                role=role,
            ),
        )
        db.commit()
        set_current_organization_id(db, organization_id)
    set_actor_audit_context(db, user_id=user.id, role=role)
    audit_log_service.create_audit_log(
        db,
        AuditLogCreate(
            actor=user.email,
            action=AuditAction.USER_CREATED,
            entity_type="user",
            entity_id=user.id,
            after=serialize_user(user),
        ),
    )
    return user


def list_users(
    db: Session,
    organization_id: UUID,
    *,
    limit: int,
    offset: int,
) -> tuple[list[UserRead], int]:
    users_and_memberships, total = organization_repository.list_active_membership_users(
        db,
        organization_id,
        limit=limit,
        offset=offset,
    )
    organization = organization_repository.get_organization_by_id(db, organization_id)
    if organization is None:
        return [], 0
    return [
        organization_member_read(user, membership, organization)
        for user, membership in users_and_memberships
    ], total


def get_user_by_id(db: Session, organization_id: UUID, user_id: UUID) -> UserRead:
    user = organization_repository.get_active_membership_user(db, organization_id, user_id)
    membership = organization_repository.get_active_membership(db, organization_id, user_id)
    organization = organization_repository.get_organization_by_id(db, organization_id)
    if user is None or membership is None or organization is None:
        raise UserNotFoundError
    return organization_member_read(user, membership, organization)


def update_user(
    db: Session,
    organization_id: UUID,
    user_id: UUID,
    update: UserUpdate,
    actor: User,
) -> UserRead:
    user = organization_repository.get_active_membership_user(db, organization_id, user_id)
    membership = organization_repository.get_active_membership(db, organization_id, user_id)
    organization = organization_repository.get_organization_by_id(db, organization_id)
    if user is None or membership is None or organization is None:
        raise UserNotFoundError
    before_read = organization_member_read(user, membership, organization)
    before = before_read.model_dump(mode="json")
    values = update.model_dump(exclude_unset=True)
    if "full_name" in values:
        raise GlobalUserIdentityUpdateNotAllowedError

    updated_role = values.get("role")
    is_deactivation = values.get("is_active") is False
    if (
        membership.role == UserRole.ADMIN
        and (updated_role not in {None, UserRole.ADMIN} or is_deactivation)
        and organization_repository.lock_active_admin_memberships(db, organization_id) <= 1
    ):
        raise LastOrganizationAdminError

    membership_values = {
        field: value
        for field, value in values.items()
        if field in {"role", "is_active"}
    }
    action = (
        AuditAction.USER_DEACTIVATED
        if is_deactivation and before_read.is_active
        else AuditAction.USER_UPDATED
    )
    if action == AuditAction.USER_DEACTIVATED:
        try:
            updated_membership = organization_repository.update_membership_pending(
                db,
                membership,
                membership_values,
            )
            after = organization_member_read(user, updated_membership, organization)
            audit_log_service.create_critical_audit_log(
                db,
                AuditLogCreate(
                    actor=actor.email,
                    action=action,
                    entity_type="user",
                    entity_id=user.id,
                    before=before,
                    after=after.model_dump(mode="json"),
                ),
            )
            db.commit()
            db.refresh(updated_membership)
        except Exception:
            db.rollback()
            raise
        return organization_member_read(user, updated_membership, organization)

    updated_membership = organization_repository.update_membership_pending(
        db,
        membership,
        membership_values,
    )
    db.commit()
    db.refresh(updated_membership)
    after = organization_member_read(user, updated_membership, organization)
    audit_create = AuditLogCreate(
        actor=actor.email,
        action=action,
        entity_type="user",
        entity_id=user.id,
        before=before,
        after=after.model_dump(mode="json"),
    )
    audit_log_service.create_audit_log(db, audit_create)
    return after
