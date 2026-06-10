import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.tenancy import get_current_organization_id, set_current_organization_id
from app.db.session import get_db
from app.models.organization import Organization, OrganizationMembership
from app.models.user import User, UserRole
from app.repositories import organizations as organization_repository
from app.repositories import users as user_repository

password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
security_logger = logging.getLogger("agenthq.security")
AUTH_ACTOR_USER_ID_KEY = "authorization_actor_user_id"
AUTH_REQUEST_ID_KEY = "authorization_request_id"


class OrgPermission(StrEnum):
    MANAGE_MEMBERS = "manage_members"
    MANAGE_INVITES = "manage_invites"
    MANAGE_AGENTS = "manage_agents"
    MANAGE_MCP_SERVERS = "manage_mcp_servers"
    MANAGE_POLICIES = "manage_policies"
    MANAGE_APPROVALS = "manage_approvals"
    MANAGE_EXECUTIONS = "manage_executions"
    MANAGE_INCIDENTS = "manage_incidents"
    VIEW_INCIDENTS = "view_incidents"
    VIEW_AUDIT_LOGS = "view_audit_logs"
    VIEW_COMPLIANCE = "view_compliance"
    VIEW_DASHBOARD = "view_dashboard"


ROLE_PERMISSIONS: dict[UserRole, frozenset[OrgPermission]] = {
    UserRole.ADMIN: frozenset(OrgPermission),
    UserRole.AUDITOR: frozenset(
        {
            OrgPermission.VIEW_INCIDENTS,
            OrgPermission.VIEW_AUDIT_LOGS,
            OrgPermission.VIEW_COMPLIANCE,
            OrgPermission.VIEW_DASHBOARD,
        }
    ),
    UserRole.OPERATOR: frozenset(
        {
            OrgPermission.MANAGE_APPROVALS,
            OrgPermission.MANAGE_EXECUTIONS,
            OrgPermission.MANAGE_INCIDENTS,
            OrgPermission.VIEW_INCIDENTS,
            OrgPermission.VIEW_DASHBOARD,
        }
    ),
    UserRole.AGENT_OWNER: frozenset(
        {
            OrgPermission.MANAGE_AGENTS,
            OrgPermission.VIEW_DASHBOARD,
        }
    ),
}


@dataclass(frozen=True)
class CurrentOrganizationContext:
    current_user: User
    current_organization: Organization | None
    current_membership: OrganizationMembership | None
    current_role: UserRole


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


def create_access_token(user: User) -> str:
    settings = get_settings()
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode(
        {"sub": str(user.id), "role": user.role.value, "exp": expires_at},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    settings = get_settings()
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired access token.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        user_id = payload.get("sub")
        if not isinstance(user_id, str):
            raise credentials_error
    except InvalidTokenError as exc:
        raise credentials_error from exc

    try:
        parsed_user_id = UUID(user_id)
    except ValueError as exc:
        raise credentials_error from exc
    user = user_repository.get_user_by_id(db, parsed_user_id)
    if user is None or not user.is_active:
        raise credentials_error
    return user


def _log_access_denied(
    request: Request,
    context: CurrentOrganizationContext,
    *,
    attempted_action: str,
) -> None:
    security_logger.warning(
        "security_org_access_denied actor_user_id=%s attempted_action=%s "
        "organization_id=%s request_id=%s path=%s",
        context.current_user.id,
        attempted_action,
        context.current_organization.id if context.current_organization else "none",
        request.headers.get("X-Request-ID", "none"),
        request.url.path,
    )


def require_org_role(*roles: UserRole) -> Callable[..., User]:
    allowed_roles = set(roles)

    def dependency(
        request: Request,
        context: Annotated[CurrentOrganizationContext, Depends(require_org_member)],
    ) -> User:
        if context.current_role not in allowed_roles:
            _log_access_denied(
                request,
                context,
                attempted_action=(
                    f"require_org_role:{','.join(sorted(role.value for role in roles))}"
                ),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions.",
            )
        return context.current_user

    return dependency


def require_org_permission(permission: OrgPermission) -> Callable[..., User]:
    def dependency(
        request: Request,
        context: Annotated[CurrentOrganizationContext, Depends(require_org_member)],
    ) -> User:
        if permission not in ROLE_PERMISSIONS[context.current_role]:
            _log_access_denied(request, context, attempted_action=permission.value)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions.",
            )
        return context.current_user

    return dependency


def require_roles(*roles: UserRole) -> Callable[..., User]:
    """Compatibility alias for routes that still express access as role lists."""
    return require_org_role(*roles)


def get_current_organization_context(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CurrentOrganizationContext:
    memberships = organization_repository.list_active_memberships_for_user(db, current_user.id)
    if len(memberships) == 1:
        membership, organization = memberships[0]
        return CurrentOrganizationContext(
            current_user=current_user,
            current_organization=organization,
            current_membership=membership,
            current_role=membership.role,
        )
    return CurrentOrganizationContext(
        current_user=current_user,
        current_organization=None,
        current_membership=None,
        current_role=current_user.role,
    )


def require_org_member(
    request: Request,
    context: Annotated[CurrentOrganizationContext, Depends(get_current_organization_context)],
    db: Annotated[Session, Depends(get_db)],
) -> CurrentOrganizationContext:
    if context.current_organization is not None and context.current_membership is not None:
        set_current_organization_id(db, context.current_organization.id)
        db.info[AUTH_ACTOR_USER_ID_KEY] = context.current_user.id
        db.info[AUTH_REQUEST_ID_KEY] = request.headers.get("X-Request-ID", "none")
        return context

    if not get_settings().is_production:
        active_organization_count = organization_repository.count_active_organizations(db)
        if active_organization_count <= 1:
            organization_id = get_current_organization_id(db)
            organization = organization_repository.get_organization_by_id(db, organization_id)
            existing_membership = organization_repository.get_membership(
                db,
                organization_id,
                context.current_user.id,
            )
            if (
                organization is not None
                and organization.slug == "default-organization"
                and existing_membership is None
            ):
                membership = organization_repository.create_membership_pending(
                    db,
                    OrganizationMembership(
                        organization_id=organization.id,
                        user_id=context.current_user.id,
                        role=context.current_user.role,
                    ),
                )
                db.commit()
                set_current_organization_id(db, organization.id)
                db.info[AUTH_ACTOR_USER_ID_KEY] = context.current_user.id
                db.info[AUTH_REQUEST_ID_KEY] = request.headers.get("X-Request-ID", "none")
                security_logger.warning(
                    "security_legacy_default_membership_created actor_user_id=%s "
                    "organization_id=%s",
                    context.current_user.id,
                    organization.id,
                )
                return CurrentOrganizationContext(
                    current_user=context.current_user,
                    current_organization=organization,
                    current_membership=membership,
                    current_role=membership.role,
                )

    _log_access_denied(request, context, attempted_action="require_org_member")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Organization membership required.",
    )


def require_current_organization(
    context: Annotated[CurrentOrganizationContext, Depends(require_org_member)],
) -> CurrentOrganizationContext:
    """Compatibility alias for the explicit active-membership dependency."""
    return context


def require_current_organization_admin(
    request: Request,
    context: Annotated[CurrentOrganizationContext, Depends(require_org_member)],
) -> CurrentOrganizationContext:
    if context.current_role != UserRole.ADMIN:
        _log_access_denied(request, context, attempted_action=OrgPermission.MANAGE_INVITES.value)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization admin access required.",
        )
    return context


def assert_resource_in_org(
    db: Session,
    resource: object,
    *,
    resource_name: str,
) -> None:
    organization_id = getattr(resource, "organization_id", None)
    if organization_id != db.info.get("organization_id"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{resource_name} not found.",
        )


def log_resource_access_denied(
    db: Session,
    *,
    attempted_action: str,
    target_resource: str,
) -> None:
    organization_id = db.info.get("organization_id")
    if organization_id is None:
        return
    security_logger.warning(
        "security_resource_access_denied actor_user_id=%s attempted_action=%s "
        "target_resource=%s organization_id=%s request_id=%s",
        db.info.get(AUTH_ACTOR_USER_ID_KEY, "unknown"),
        attempted_action,
        target_resource,
        organization_id,
        db.info.get(AUTH_REQUEST_ID_KEY, "none"),
    )


def ensure_agent_access(
    agent_id: UUID,
    context: Annotated[CurrentOrganizationContext, Depends(require_org_member)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    if context.current_role == UserRole.ADMIN:
        return
    from app.repositories import agents as agent_repository

    agent = agent_repository.get_agent_by_id(db, agent_id)
    if agent is None:
        log_resource_access_denied(
            db,
            attempted_action="access_agent",
            target_resource=f"agent:{agent_id}",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found.",
        )
    if agent.owner.lower() != context.current_user.email.lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent access denied.",
        )
