from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.user import User


def create_user(db: Session, user: User) -> User:
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_user_pending(db: Session, user: User) -> User:
    db.add(user)
    db.flush()
    return user


def count_users(db: Session, *, active_only: bool = False) -> int:
    statement = select(func.count()).select_from(User)
    if active_only:
        statement = statement.where(User.is_active.is_(True))
    return db.scalar(statement) or 0


def list_users(db: Session, *, limit: int, offset: int) -> tuple[list[User], int]:
    statement = select(User).order_by(User.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(statement).all()), count_users(db)


def get_user_by_id(db: Session, user_id: UUID) -> User | None:
    return db.scalar(select(User).where(User.id == user_id))


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.lower()))


def update_user(db: Session, user: User, values: dict[str, object]) -> User:
    for field, value in values.items():
        setattr(user, field, value)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user_pending(db: Session, user: User, values: dict[str, object]) -> User:
    for field, value in values.items():
        setattr(user, field, value)
    db.add(user)
    db.flush()
    return user
