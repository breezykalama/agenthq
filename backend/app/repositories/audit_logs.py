from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditAction, AuditLog
from app.schemas.audit_log import AuditLogCreate


def create_audit_log(db: Session, audit_log_create: AuditLogCreate) -> AuditLog:
    audit_log = AuditLog(**audit_log_create.model_dump())
    db.add(audit_log)
    db.commit()
    db.refresh(audit_log)
    return audit_log


def list_audit_logs(
    db: Session,
    *,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    action: AuditAction | None = None,
    actor: str | None = None,
) -> tuple[list[AuditLog], int]:
    filters = []
    if entity_type is not None:
        filters.append(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        filters.append(AuditLog.entity_id == entity_id)
    if action is not None:
        filters.append(AuditLog.action == action)
    if actor is not None:
        filters.append(AuditLog.actor == actor)

    statement = select(AuditLog).where(*filters).order_by(AuditLog.created_at.desc())
    count_statement = select(func.count()).select_from(AuditLog).where(*filters)

    audit_logs = list(db.scalars(statement).all())
    total = db.scalar(count_statement) or 0
    return audit_logs, total


def get_audit_log_by_id(db: Session, audit_log_id: UUID) -> AuditLog | None:
    statement = select(AuditLog).where(AuditLog.id == audit_log_id)
    return db.scalar(statement)
