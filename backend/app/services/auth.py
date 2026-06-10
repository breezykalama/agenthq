from sqlalchemy.orm import Session

from app.core.audit_context import set_actor_audit_context
from app.core.security import create_access_token, verify_password
from app.core.tenancy import set_current_organization_id
from app.models.audit_log import AuditAction
from app.repositories import organizations as organization_repository
from app.repositories import users as user_repository
from app.schemas.audit_log import AuditLogCreate
from app.schemas.user import TokenResponse, UserLogin
from app.services import audit_logs as audit_log_service


class InvalidCredentialsError(Exception):
    pass


def login(db: Session, credentials: UserLogin) -> TokenResponse:
    user = user_repository.get_user_by_email(db, credentials.email.lower())
    if (
        user is None
        or not user.is_active
        or not verify_password(credentials.password, user.password_hash)
    ):
        raise InvalidCredentialsError
    memberships = organization_repository.list_active_memberships_for_user(db, user.id)
    if len(memberships) == 1:
        membership, organization = memberships[0]
        set_current_organization_id(db, organization.id)
        set_actor_audit_context(db, user_id=user.id, role=membership.role)
    else:
        set_actor_audit_context(db, user_id=user.id, role=user.role)
    audit_log_service.create_audit_log(
        db,
        AuditLogCreate(
            actor=user.email,
            action=AuditAction.USER_LOGIN,
            entity_type="user",
            entity_id=user.id,
        ),
    )
    return TokenResponse(access_token=create_access_token(user))
