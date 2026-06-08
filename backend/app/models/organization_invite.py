from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.agent import utc_now
from app.models.user import UserRole


class OrganizationInviteStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    REVOKED = "revoked"


class OrganizationInvite(Base):
    __tablename__ = "organization_invites"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(
            UserRole,
            name="organization_invite_role",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[OrganizationInviteStatus] = mapped_column(
        Enum(
            OrganizationInviteStatus,
            name="organization_invite_status",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        default=OrganizationInviteStatus.PENDING,
    )
    invited_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


Index("ix_organization_invites_token_hash", OrganizationInvite.token_hash, unique=True)
Index("ix_organization_invites_organization_id", OrganizationInvite.organization_id)
Index("ix_organization_invites_email", OrganizationInvite.email)
Index("ix_organization_invites_status", OrganizationInvite.status)
Index(
    "ix_organization_invites_unique_pending_email",
    OrganizationInvite.organization_id,
    OrganizationInvite.email,
    unique=True,
    postgresql_where=OrganizationInvite.status == OrganizationInviteStatus.PENDING,
    sqlite_where=OrganizationInvite.status == OrganizationInviteStatus.PENDING,
)
