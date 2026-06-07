from uuid import UUID

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.audit_log import AuditAction, JsonObject
from app.models.user import User, UserRole
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


def list_users(db: Session) -> tuple[list[User], int]:
    return user_repository.list_users(db)


def get_user_by_id(db: Session, user_id: UUID) -> User:
    user = user_repository.get_user_by_id(db, user_id)
    if user is None:
        raise UserNotFoundError
    return user


def update_user(db: Session, user_id: UUID, update: UserUpdate, actor: User) -> User:
    user = get_user_by_id(db, user_id)
    before = serialize_user(user)
    values = update.model_dump(exclude_unset=True)
    updated_user = user_repository.update_user(db, user, values)
    action = (
        AuditAction.USER_DEACTIVATED
        if values.get("is_active") is False and before["is_active"] is True
        else AuditAction.USER_UPDATED
    )
    audit_log_service.create_audit_log(
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
    return updated_user
