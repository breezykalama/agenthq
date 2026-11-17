from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.agent import utc_now


class EmailVerificationTokenStatus(StrEnum):
    PENDING = "pending"
    USED = "used"
    EXPIRED = "expired"
    REVOKED = "revoked"


class PasswordResetTokenStatus(StrEnum):
    PENDING = "pending"
    USED = "used"
    EXPIRED = "expired"


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[EmailVerificationTokenStatus] = mapped_column(
        Enum(
            EmailVerificationTokenStatus,
            name="email_verification_token_status",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        default=EmailVerificationTokenStatus.PENDING,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[PasswordResetTokenStatus] = mapped_column(
        Enum(
            PasswordResetTokenStatus,
            name="password_reset_token_status",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        default=PasswordResetTokenStatus.PENDING,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


Index("ix_email_verification_tokens_user_id", EmailVerificationToken.user_id)
Index("ix_email_verification_tokens_status", EmailVerificationToken.status)
Index("ix_password_reset_tokens_user_id", PasswordResetToken.user_id)
Index("ix_password_reset_tokens_status", PasswordResetToken.status)
