from uuid import UUID

from sqlalchemy.orm import Session

from app.models.audit_log import AuditAction, AuditLog
from app.repositories import audit_logs as audit_log_repository
from app.schemas.audit_log import AuditLogCreate


class AuditLoggingError(Exception):
    pass


def create_audit_log(db: Session, audit_log_create: AuditLogCreate) -> AuditLog:
    return audit_log_repository.create_audit_log(db, audit_log_create)


def create_critical_audit_log(db: Session, audit_log_create: AuditLogCreate) -> AuditLog:
    try:
        return audit_log_repository.create_audit_log_pending(db, audit_log_create)
    except Exception as exc:
        db.rollback()
        raise AuditLoggingError("Critical action could not be audited.") from exc


def list_audit_logs(
    db: Session,
    *,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    action: AuditAction | None = None,
    actor: str | None = None,
    limit: int,
    offset: int,
) -> tuple[list[AuditLog], int]:
    return audit_log_repository.list_audit_logs(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor=actor,
        limit=limit,
        offset=offset,
    )


def get_audit_log_by_id(db: Session, audit_log_id: UUID) -> AuditLog | None:
    return audit_log_repository.get_audit_log_by_id(db, audit_log_id)
