from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.audit_redaction import redact_audit_snapshot
from app.core.tenancy import get_current_organization_id
from app.models.governance_alert import (
    GovernanceAlert,
    GovernanceAlertSeverity,
    GovernanceAlertStatus,
    GovernanceAlertType,
)

ACTIVE_ALERT_STATUSES = (GovernanceAlertStatus.OPEN, GovernanceAlertStatus.ACKNOWLEDGED)


def create_alert_pending(
    db: Session,
    *,
    alert_type: GovernanceAlertType,
    severity: GovernanceAlertSeverity,
    agent_id: UUID | None,
    tool_id: UUID | None,
    mcp_server_id: UUID | None,
    title: str,
    description: str,
    metadata: dict[str, object] | None,
) -> GovernanceAlert:
    alert = GovernanceAlert(
        organization_id=get_current_organization_id(db),
        alert_type=alert_type,
        severity=severity,
        agent_id=agent_id,
        tool_id=tool_id,
        mcp_server_id=mcp_server_id,
        title=title,
        description=description,
        alert_metadata=redact_audit_snapshot(metadata),
    )
    db.add(alert)
    db.flush()
    return alert


def get_active_alert(
    db: Session,
    *,
    alert_type: GovernanceAlertType,
    tool_id: UUID | None,
    mcp_server_id: UUID | None,
) -> GovernanceAlert | None:
    return db.scalar(
        select(GovernanceAlert).where(
            GovernanceAlert.organization_id == get_current_organization_id(db),
            GovernanceAlert.alert_type == alert_type,
            GovernanceAlert.tool_id == tool_id,
            GovernanceAlert.mcp_server_id == mcp_server_id,
            GovernanceAlert.status.in_(ACTIVE_ALERT_STATUSES),
        )
    )


def get_alert_by_id(db: Session, alert_id: UUID) -> GovernanceAlert | None:
    return db.scalar(
        select(GovernanceAlert).where(
            GovernanceAlert.organization_id == get_current_organization_id(db),
            GovernanceAlert.id == alert_id,
        )
    )


def update_alert_pending(
    db: Session,
    alert: GovernanceAlert,
    values: dict[str, object],
) -> GovernanceAlert:
    for field, value in values.items():
        setattr(alert, field, value)
    db.add(alert)
    db.flush()
    return alert


def list_alerts(
    db: Session,
    *,
    status: GovernanceAlertStatus | None,
    severity: GovernanceAlertSeverity | None,
    alert_type: GovernanceAlertType | None,
    tool_id: UUID | None = None,
    limit: int,
    offset: int,
) -> tuple[list[GovernanceAlert], int]:
    filters: list[ColumnElement[bool]] = [
        GovernanceAlert.organization_id == get_current_organization_id(db)
    ]
    if status is not None:
        filters.append(GovernanceAlert.status == status)
    if severity is not None:
        filters.append(GovernanceAlert.severity == severity)
    if alert_type is not None:
        filters.append(GovernanceAlert.alert_type == alert_type)
    if tool_id is not None:
        filters.append(GovernanceAlert.tool_id == tool_id)
    statement = (
        select(GovernanceAlert)
        .where(*filters)
        .order_by(GovernanceAlert.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    count_statement = select(func.count()).select_from(GovernanceAlert).where(*filters)
    return list(db.scalars(statement).all()), db.scalar(count_statement) or 0


def active_alert_ids_by_tool(db: Session) -> dict[UUID, list[UUID]]:
    statement = select(GovernanceAlert.tool_id, GovernanceAlert.id).where(
        GovernanceAlert.organization_id == get_current_organization_id(db),
        GovernanceAlert.tool_id.is_not(None),
        GovernanceAlert.status.in_(ACTIVE_ALERT_STATUSES),
    )
    result: dict[UUID, list[UUID]] = {}
    for tool_id, alert_id in db.execute(statement):
        if tool_id is not None:
            result.setdefault(tool_id, []).append(alert_id)
    return result


def get_alert_metrics(db: Session) -> tuple[int, int, int]:
    row = db.execute(
        select(
            func.count().filter(GovernanceAlert.status.in_(ACTIVE_ALERT_STATUSES)),
            func.count().filter(
                GovernanceAlert.status.in_(ACTIVE_ALERT_STATUSES),
                GovernanceAlert.severity == GovernanceAlertSeverity.CRITICAL,
            ),
            func.count().filter(
                GovernanceAlert.status.in_(ACTIVE_ALERT_STATUSES),
                GovernanceAlert.severity == GovernanceAlertSeverity.HIGH,
            ),
        ).where(GovernanceAlert.organization_id == get_current_organization_id(db))
    ).one()
    return row[0], row[1], row[2]
