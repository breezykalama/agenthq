from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.pagination import PaginationParams
from app.core.security import OrgPermission, require_current_organization, require_org_permission
from app.db.session import get_db
from app.models.audit_log import AuditAction
from app.models.governance_alert import (
    GovernanceAlertSeverity,
    GovernanceAlertStatus,
    GovernanceAlertType,
)
from app.schemas.governance_alert import (
    GovernanceAlertListResponse,
    GovernanceAlertRead,
    GovernanceHealthScore,
)
from app.services import governance_alerts as alert_service

router = APIRouter(
    prefix="/api/v1/governance-alerts",
    tags=["governance-alerts"],
    dependencies=[
        Depends(require_current_organization),
        Depends(require_org_permission(OrgPermission.VIEW_ALERTS)),
    ],
)
health_router = APIRouter(
    prefix="/api/v1",
    tags=["governance-alerts"],
    dependencies=[
        Depends(require_current_organization),
        Depends(require_org_permission(OrgPermission.VIEW_ALERTS)),
    ],
)
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.get("", response_model=GovernanceAlertListResponse)
def list_governance_alerts(
    db: DatabaseSession,
    pagination: PaginationParams,
    status_filter: Annotated[GovernanceAlertStatus | None, Query(alias="status")] = None,
    severity: Annotated[GovernanceAlertSeverity | None, Query()] = None,
    alert_type: Annotated[GovernanceAlertType | None, Query()] = None,
    tool_id: Annotated[UUID | None, Query()] = None,
) -> GovernanceAlertListResponse:
    alerts, total = alert_service.list_alerts(
        db,
        status=status_filter,
        severity=severity,
        alert_type=alert_type,
        tool_id=tool_id,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    return GovernanceAlertListResponse(
        items=[GovernanceAlertRead.model_validate(alert) for alert in alerts],
        total=total,
    )


@router.get("/{alert_id}", response_model=GovernanceAlertRead)
def get_governance_alert(alert_id: UUID, db: DatabaseSession) -> GovernanceAlertRead:
    try:
        return GovernanceAlertRead.model_validate(alert_service.get_alert(db, alert_id))
    except alert_service.GovernanceAlertNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found.",
        ) from exc


def transition(
    db: Session,
    alert_id: UUID,
    *,
    target_status: GovernanceAlertStatus,
    action: AuditAction,
) -> GovernanceAlertRead:
    try:
        return GovernanceAlertRead.model_validate(
            alert_service.transition_alert(
                db,
                alert_id,
                target_status=target_status,
                action=action,
            )
        )
    except alert_service.GovernanceAlertNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found.",
        ) from exc
    except alert_service.InvalidGovernanceAlertTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Alert status transition is not allowed.",
        ) from exc


@router.post(
    "/{alert_id}/acknowledge",
    response_model=GovernanceAlertRead,
    dependencies=[Depends(require_org_permission(OrgPermission.MANAGE_ALERTS))],
)
def acknowledge_alert(alert_id: UUID, db: DatabaseSession) -> GovernanceAlertRead:
    return transition(
        db,
        alert_id,
        target_status=GovernanceAlertStatus.ACKNOWLEDGED,
        action=AuditAction.GOVERNANCE_ALERT_ACKNOWLEDGED,
    )


@router.post(
    "/{alert_id}/resolve",
    response_model=GovernanceAlertRead,
    dependencies=[Depends(require_org_permission(OrgPermission.MANAGE_ALERTS))],
)
def resolve_alert(alert_id: UUID, db: DatabaseSession) -> GovernanceAlertRead:
    return transition(
        db,
        alert_id,
        target_status=GovernanceAlertStatus.RESOLVED,
        action=AuditAction.GOVERNANCE_ALERT_RESOLVED,
    )


@router.post(
    "/{alert_id}/reopen",
    response_model=GovernanceAlertRead,
    dependencies=[Depends(require_org_permission(OrgPermission.MANAGE_ALERTS))],
)
def reopen_alert(alert_id: UUID, db: DatabaseSession) -> GovernanceAlertRead:
    return transition(
        db,
        alert_id,
        target_status=GovernanceAlertStatus.OPEN,
        action=AuditAction.GOVERNANCE_ALERT_REOPENED,
    )


@health_router.get("/governance-health", response_model=GovernanceHealthScore)
def get_governance_health(db: DatabaseSession) -> GovernanceHealthScore:
    return alert_service.get_health(db)
