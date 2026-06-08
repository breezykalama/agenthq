from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models.organization_invite import OrganizationInvite, OrganizationInviteStatus


def create_invite_pending(db: Session, invite: OrganizationInvite) -> OrganizationInvite:
    db.add(invite)
    db.flush()
    return invite


def get_invite_by_id(
    db: Session,
    organization_id: UUID,
    invite_id: UUID,
) -> OrganizationInvite | None:
    return db.scalar(
        select(OrganizationInvite).where(
            OrganizationInvite.id == invite_id,
            OrganizationInvite.organization_id == organization_id,
        )
    )


def get_invite_by_token_hash(db: Session, token_hash: str) -> OrganizationInvite | None:
    return db.scalar(select(OrganizationInvite).where(OrganizationInvite.token_hash == token_hash))


def get_pending_invite_by_email(
    db: Session,
    organization_id: UUID,
    email: str,
) -> OrganizationInvite | None:
    return db.scalar(
        select(OrganizationInvite).where(
            OrganizationInvite.organization_id == organization_id,
            OrganizationInvite.email == email,
            OrganizationInvite.status == OrganizationInviteStatus.PENDING,
        )
    )


def list_invites(
    db: Session,
    *,
    organization_id: UUID,
    status: OrganizationInviteStatus | None,
    email: str | None,
    limit: int,
    offset: int,
) -> tuple[list[OrganizationInvite], int]:
    filters: list[ColumnElement[bool]] = [OrganizationInvite.organization_id == organization_id]
    if status is not None:
        filters.append(OrganizationInvite.status == status)
    if email is not None:
        filters.append(OrganizationInvite.email == email.lower())
    statement = (
        select(OrganizationInvite)
        .where(*filters)
        .order_by(OrganizationInvite.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    count_statement = select(func.count()).select_from(OrganizationInvite).where(*filters)
    return list(db.scalars(statement).all()), db.scalar(count_statement) or 0


def update_invite_pending(db: Session, invite: OrganizationInvite) -> OrganizationInvite:
    db.add(invite)
    db.flush()
    return invite
