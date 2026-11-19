import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit_context import set_actor_audit_context
from app.core.config import get_settings
from app.core.security import (
    CurrentOrganizationContext,
    create_access_token,
    hash_password,
    verify_password,
)
from app.core.tenancy import set_current_organization_id
from app.models.audit_log import AuditAction, JsonObject
from app.models.email_outbox import EmailOutboxKind
from app.models.organization import OrganizationMembership
from app.models.organization_invite import OrganizationInvite, OrganizationInviteStatus
from app.models.user import User, UserRole
from app.repositories import organization_invites as invite_repository
from app.repositories import organizations as organization_repository
from app.repositories import users as user_repository
from app.schemas.audit_log import AuditLogCreate
from app.schemas.organization_invite import (
    OrganizationInviteAccept,
    OrganizationInviteCreate,
    OrganizationInviteCreateResponse,
    OrganizationInviteRead,
)
from app.schemas.user import BootstrapTokenResponse, UserRead
from app.services import audit_logs as audit_log_service
from app.services import email_outbox
from app.services import organizations as organization_service
from app.services.email import EmailBackend, EmailDeliveryError, delivery_enabled


class DuplicatePendingInviteError(Exception):
    pass


class OrganizationInviteNotFoundError(Exception):
    pass


class InvalidInviteTransitionError(Exception):
    pass


class InvalidInviteTokenError(Exception):
    pass


class InviteFullNameRequiredError(Exception):
    pass


class MultipleOrganizationsNotSupportedError(Exception):
    """The invitee already has an active membership in another organization.

    Temporary safety guard: the organization-context resolver only works for users with exactly
    one active membership, so a second one would lock the user out of both organizations. The
    invite is left pending so it can be accepted once organization selection exists.
    """


class DuplicateOrganizationMembershipError(Exception):
    pass


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_expired(expires_at: datetime, now: datetime) -> bool:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= now


def serialize_invite(invite: OrganizationInvite) -> JsonObject:
    return OrganizationInviteRead.model_validate(invite).model_dump(mode="json")


def create_invite(
    db: Session,
    context: CurrentOrganizationContext,
    invite_create: OrganizationInviteCreate,
    email_backend: EmailBackend,
) -> OrganizationInviteCreateResponse:
    organization = context.current_organization
    if organization is None:
        raise OrganizationInviteNotFoundError
    email = invite_create.email.lower()
    existing = invite_repository.get_pending_invite_by_email(db, organization.id, email)
    if existing is not None:
        if not is_expired(existing.expires_at, datetime.now(UTC)):
            raise DuplicatePendingInviteError
        existing.status = OrganizationInviteStatus.EXPIRED
        invite_repository.update_invite_pending(db, existing)

    settings = get_settings()
    can_deliver = delivery_enabled(email_backend)
    if not can_deliver and settings.is_production:
        # Production never returns the raw token, so without email the invite is unusable.
        raise EmailDeliveryError("Email delivery is required in production.")
    issued = email_outbox.issue_token()
    invite = OrganizationInvite(
        organization_id=organization.id,
        email=email,
        full_name=invite_create.full_name,
        role=invite_create.role,
        token_hash=issued.token_hash,
        invited_by_user_id=context.current_user.id,
        expires_at=datetime.now(UTC) + timedelta(days=invite_create.expires_in_days),
    )
    try:
        invite_repository.create_invite_pending(db, invite)
        audit_log_service.create_critical_audit_log(
            db,
            AuditLogCreate(
                organization_id=organization.id,
                actor=context.current_user.email,
                action=AuditAction.ORGANIZATION_INVITE_CREATED,
                entity_type="organization_invite",
                entity_id=invite.id,
                after=serialize_invite(invite),
            ),
        )
        if can_deliver:
            # Same transaction as the invite: the email can only go out once both commit.
            email_outbox.enqueue(
                db,
                kind=EmailOutboxKind.ORGANIZATION_INVITE,
                token_id=invite.id,
                issued=issued,
                organization_id=organization.id,
            )
        db.commit()
        db.refresh(invite)
    except IntegrityError as exc:
        db.rollback()
        raise DuplicatePendingInviteError from exc
    except Exception:
        db.rollback()
        raise
    if can_deliver:
        email_outbox.notify_worker()
    expose_token = not settings.is_production
    return OrganizationInviteCreateResponse(
        **OrganizationInviteRead.model_validate(invite).model_dump(),
        token=issued.raw_token if expose_token else None,
        invite_url=(
            email_outbox.frontend_action_url("invite", issued.raw_token) if expose_token else None
        ),
        email_delivery="queued" if can_deliver else "disabled",
    )


def list_invites(
    db: Session,
    context: CurrentOrganizationContext,
    *,
    status: OrganizationInviteStatus | None,
    email: str | None,
    limit: int,
    offset: int,
) -> tuple[list[OrganizationInvite], int]:
    if context.current_organization is None:
        return [], 0
    return invite_repository.list_invites(
        db,
        organization_id=context.current_organization.id,
        status=status,
        email=email,
        limit=limit,
        offset=offset,
    )


def revoke_invite(
    db: Session,
    context: CurrentOrganizationContext,
    invite_id: UUID,
) -> OrganizationInvite:
    organization = context.current_organization
    if organization is None:
        raise OrganizationInviteNotFoundError
    invite = invite_repository.get_invite_by_id(db, organization.id, invite_id)
    if invite is None:
        raise OrganizationInviteNotFoundError
    if invite.status != OrganizationInviteStatus.PENDING:
        raise InvalidInviteTransitionError
    if is_expired(invite.expires_at, datetime.now(UTC)):
        invite.status = OrganizationInviteStatus.EXPIRED
        db.commit()
        raise InvalidInviteTransitionError
    before = serialize_invite(invite)
    try:
        invite.status = OrganizationInviteStatus.REVOKED
        invite_repository.update_invite_pending(db, invite)
        audit_log_service.create_critical_audit_log(
            db,
            AuditLogCreate(
                organization_id=organization.id,
                actor=context.current_user.email,
                action=AuditAction.ORGANIZATION_INVITE_REVOKED,
                entity_type="organization_invite",
                entity_id=invite.id,
                before=before,
                after=serialize_invite(invite),
            ),
        )
        db.commit()
        db.refresh(invite)
    except Exception:
        db.rollback()
        raise
    return invite


def accept_invite(
    db: Session,
    accept: OrganizationInviteAccept,
) -> BootstrapTokenResponse:
    invite = invite_repository.get_invite_by_token_hash(db, token_digest(accept.token))
    if invite is not None:
        # Lock the invite row so concurrent accepts of one token are serialized; the loser
        # re-reads a non-pending status below.
        db.refresh(invite, with_for_update=True)
    now = datetime.now(UTC)
    if (
        invite is None
        or invite.status != OrganizationInviteStatus.PENDING
        or is_expired(invite.expires_at, now)
    ):
        raise InvalidInviteTokenError
    organization = organization_repository.get_organization_by_id(db, invite.organization_id)
    if organization is None:
        raise InvalidInviteTokenError
    set_current_organization_id(db, organization.id)

    user = user_repository.get_user_by_email(db, invite.email)
    is_new_user = user is None
    if user is not None:
        # Lock the user row so every acceptance for this account is serialized. The invite lock
        # above only serializes accepts of one token; two different organizations' invites for
        # the same user would otherwise both pass the membership check below. Lock order is
        # always invite, then user.
        db.refresh(user, with_for_update=True)
        if not user.is_active or not verify_password(accept.password, user.password_hash):
            raise InvalidInviteTokenError
        if organization_repository.get_active_membership(db, invite.organization_id, user.id):
            raise DuplicateOrganizationMembershipError
        # Same membership set the organization-context resolver uses (active memberships in
        # organizations that are not deleted), so the guard blocks exactly the lockout case.
        if any(
            organization.id != invite.organization_id
            for _, organization in organization_repository.list_active_memberships_for_user(
                db, user.id
            )
        ):
            # Release the row locks without writing anything: the invite stays pending.
            db.rollback()
            raise MultipleOrganizationsNotSupportedError
    else:
        full_name = invite.full_name or accept.full_name
        if not full_name:
            raise InviteFullNameRequiredError
        user = User(
            email=invite.email,
            full_name=full_name,
            password_hash=hash_password(accept.password),
            role=UserRole.AGENT_OWNER,
            email_verified=True,
            email_verified_at=now,
        )
    set_actor_audit_context(db, user_id=user.id, role=invite.role)

    before = serialize_invite(invite)
    try:
        if is_new_user:
            user_repository.create_user_pending(db, user)
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
        membership = organization_repository.create_membership_pending(
            db,
            OrganizationMembership(
                organization_id=invite.organization_id,
                user_id=user.id,
                role=invite.role,
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
                after=organization_service.serialize_membership(membership, organization),
            ),
        )
        invite.status = OrganizationInviteStatus.ACCEPTED
        invite.accepted_at = now
        invite_repository.update_invite_pending(db, invite)
        audit_log_service.create_critical_audit_log(
            db,
            AuditLogCreate(
                organization_id=organization.id,
                actor=user.email,
                action=AuditAction.ORGANIZATION_INVITE_ACCEPTED,
                entity_type="organization_invite",
                entity_id=invite.id,
                before=before,
                after=serialize_invite(invite),
            ),
        )
        db.commit()
        db.refresh(user)
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateOrganizationMembershipError from exc
    except Exception:
        db.rollback()
        raise
    return BootstrapTokenResponse(
        access_token=create_access_token(user),
        user=organization_service.user_read_with_membership(db, user),
    )
