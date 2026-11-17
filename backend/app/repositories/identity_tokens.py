from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.identity_token import EmailVerificationToken, PasswordResetToken


def create_email_verification_token_pending(
    db: Session,
    token: EmailVerificationToken,
) -> EmailVerificationToken:
    db.add(token)
    db.flush()
    return token


def get_email_verification_by_hash(
    db: Session,
    token_hash: str,
) -> EmailVerificationToken | None:
    return db.scalar(
        select(EmailVerificationToken).where(EmailVerificationToken.token_hash == token_hash)
    )


def list_email_verifications_for_user(
    db: Session,
    user_id: UUID,
) -> list[EmailVerificationToken]:
    return list(
        db.scalars(
            select(EmailVerificationToken).where(EmailVerificationToken.user_id == user_id)
        ).all()
    )


def create_password_reset_token_pending(
    db: Session,
    token: PasswordResetToken,
) -> PasswordResetToken:
    db.add(token)
    db.flush()
    return token


def get_password_reset_by_hash(db: Session, token_hash: str) -> PasswordResetToken | None:
    return db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash))


def list_password_resets_for_user(db: Session, user_id: UUID) -> list[PasswordResetToken]:
    return list(
        db.scalars(select(PasswordResetToken).where(PasswordResetToken.user_id == user_id)).all()
    )
