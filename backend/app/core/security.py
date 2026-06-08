from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.tenancy import get_current_organization_id, set_current_organization_id
from app.db.session import get_db
from app.models.organization import Organization, OrganizationMembership
from app.models.user import User, UserRole
from app.repositories import agents as agent_repository
from app.repositories import organizations as organization_repository
from app.repositories import users as user_repository

password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


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


def require_roles(*roles: UserRole) -> Callable[..., User]:
    allowed_roles = set(roles)

    def dependency(
        context: Annotated[CurrentOrganizationContext, Depends(get_current_organization_context)],
    ) -> User:
        if context.current_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions.",
            )
        return context.current_user

    return dependency


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


def require_current_organization_admin(
    context: Annotated[CurrentOrganizationContext, Depends(get_current_organization_context)],
) -> CurrentOrganizationContext:
    if (
        context.current_organization is None
        or context.current_membership is None
        or context.current_role != UserRole.ADMIN
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization admin access required.",
        )
    return context


def require_current_organization(
    context: Annotated[CurrentOrganizationContext, Depends(get_current_organization_context)],
    db: Annotated[Session, Depends(get_db)],
) -> CurrentOrganizationContext:
    if context.current_organization is not None and context.current_membership is not None:
        set_current_organization_id(db, context.current_organization.id)
        return context

    active_organization_count = organization_repository.count_active_organizations(db)
    if active_organization_count <= 1:
        organization_id = get_current_organization_id(db)
        organization = organization_repository.get_organization_by_id(db, organization_id)
        if organization is None or (
            active_organization_count == 1 and organization.slug != "default-organization"
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization membership required.",
            )
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
        return CurrentOrganizationContext(
            current_user=context.current_user,
            current_organization=organization,
            current_membership=membership,
            current_role=membership.role,
        )

    if context.current_organization is None or context.current_membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization membership required.",
        )
    return context


def ensure_agent_access(
    agent_id: UUID,
    context: Annotated[CurrentOrganizationContext, Depends(get_current_organization_context)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    if context.current_organization is not None:
        set_current_organization_id(db, context.current_organization.id)
    if context.current_role == UserRole.ADMIN:
        return
    agent = agent_repository.get_agent_by_id(db, agent_id)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found.",
        )
    if agent.owner.lower() != context.current_user.email.lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent access denied.",
        )
