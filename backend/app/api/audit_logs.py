from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.pagination import PaginationParams
from app.core.security import OrgPermission, require_current_organization, require_org_permission
from app.db.session import get_db
from app.models.audit_log import AuditAction
from app.schemas.audit_log import AuditLogListResponse, AuditLogRead
from app.services import audit_logs as audit_log_service

router = APIRouter(
    prefix="/api/v1/audit-logs",
    tags=["audit-logs"],
    dependencies=[
        Depends(require_current_organization),
        Depends(require_org_permission(OrgPermission.VIEW_AUDIT_LOGS)),
    ],
)
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.get("", response_model=AuditLogListResponse)
def list_audit_logs(
    db: DatabaseSession,
    pagination: PaginationParams,
    entity_type: Annotated[str | None, Query()] = None,
    entity_id: Annotated[UUID | None, Query()] = None,
    action: Annotated[AuditAction | None, Query()] = None,
    actor: Annotated[str | None, Query()] = None,
) -> AuditLogListResponse:
    audit_logs, total = audit_log_service.list_audit_logs(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor=actor,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    return AuditLogListResponse(
        items=[AuditLogRead.model_validate(audit_log) for audit_log in audit_logs],
        total=total,
    )
