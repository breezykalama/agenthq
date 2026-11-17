from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.agent import utc_now


class EmailOutboxKind(StrEnum):
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"
    ORGANIZATION_INVITE = "organization_invite"


class EmailOutboxStatus(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EmailOutbox(Base):
    """Durable, transactional email queue.

    Rows never contain a raw token or the rendered message. ``token_nonce`` is a random value
    from which the raw token is re-derived with a server-side HMAC key at send time; it is
    cleared as soon as the row reaches a terminal state.
    """

    __tablename__ = "email_outbox"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    kind: Mapped[EmailOutboxKind] = mapped_column(
        Enum(
            EmailOutboxKind,
            name="email_outbox_kind",
            native_enum=False,
            length=32,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    status: Mapped[EmailOutboxStatus] = mapped_column(
        Enum(
            EmailOutboxStatus,
            name="email_outbox_status",
            native_enum=False,
            length=16,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        default=EmailOutboxStatus.PENDING,
    )
    token_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    token_nonce: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    organization_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


UniqueConstraint(EmailOutbox.kind, EmailOutbox.token_id, name="uq_email_outbox_kind_token")
Index("ix_email_outbox_status_next_attempt_at", EmailOutbox.status, EmailOutbox.next_attempt_at)
