from uuid import UUID

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.core.tenancy import get_current_organization_id, set_current_organization_id
from app.models.audit_log import AuditAction, JsonObject
from app.models.organization import OrganizationMembership
from app.models.user import User, UserRole
from app.repositories import organizations as organization_repository
from app.repositories import users as user_repository
from app.schemas.audit_log import AuditLogCreate
from app.schemas.user import UserRead, UserRegister, UserUpdate
from app.services import audit_logs as audit_log_service


class UserNotFoundError(Exception):
    pass


class DuplicateUserEmailError(Exception):
    pass


def serialize_user(user: User) -> JsonObject:
    return UserRead.model_validate(user).model_dump(mode="json")


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


def list_users(db: Session, *, limit: int, offset: int) -> tuple[list[User], int]:
    return user_repository.list_users(db, limit=limit, offset=offset)


def get_user_by_id(db: Session, user_id: UUID) -> User:
    user = user_repository.get_user_by_id(db, user_id)
    if user is None:
        raise UserNotFoundError
    return user


def update_user(db: Session, user_id: UUID, update: UserUpdate, actor: User) -> User:
    user = get_user_by_id(db, user_id)
    before = serialize_user(user)
    values = update.model_dump(exclude_unset=True)
    updated_role = values.get("role")
    if isinstance(updated_role, UserRole):
        memberships = organization_repository.list_active_memberships_for_user(db, user.id)
        if len(memberships) == 1 and memberships[0][1].slug == "default-organization":
            memberships[0][0].role = updated_role
            db.add(memberships[0][0])
    action = (
        AuditAction.USER_DEACTIVATED
        if values.get("is_active") is False and before["is_active"] is True
        else AuditAction.USER_UPDATED
    )
    if action == AuditAction.USER_DEACTIVATED:
        try:
            updated_user = user_repository.update_user_pending(db, user, values)
            audit_log_service.create_critical_audit_log(
                db,
                AuditLogCreate(
                    actor=actor.email,
                    action=action,
                    entity_type="user",
                    entity_id=updated_user.id,
                    before=before,
                    after=serialize_user(updated_user),
                ),
            )
            db.commit()
            db.refresh(updated_user)
        except Exception:
            db.rollback()
            raise
        return updated_user

    updated_user = user_repository.update_user(db, user, values)
    audit_create = AuditLogCreate(
        actor=actor.email,
        action=action,
        entity_type="user",
        entity_id=updated_user.id,
        before=before,
        after=serialize_user(updated_user),
    )
    audit_log_service.create_audit_log(db, audit_create)
    return updated_user
