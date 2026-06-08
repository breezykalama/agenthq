from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.agent import AgentRiskLevel
from app.models.incident import Incident, IncidentStatus
from app.repositories import compliance as compliance_repository
from app.schemas.agent import AgentRead
from app.schemas.compliance import (
    AgentComplianceReport,
    ComplianceIncidentListResponse,
    ComplianceIncidentRead,
    ComplianceSummary,
)


@dataclass(frozen=True)
class DateRange:
    start_at: datetime | None
    end_at: datetime | None


class InvalidComplianceDateRangeError(Exception):
    pass


class ComplianceAgentNotFoundError(Exception):
    pass


def get_summary(
    db: Session,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    agent_id: UUID | None = None,
) -> ComplianceSummary:
    date_range = build_date_range(start_date, end_date)
    metrics = compliance_repository.get_summary_metrics(
        db,
        start_at=date_range.start_at,
        end_at=date_range.end_at,
        agent_id=agent_id,
    )
    return ComplianceSummary(**metrics.__dict__)


def get_agent_report(db: Session, agent_id: UUID) -> AgentComplianceReport:
    agent = compliance_repository.get_agent(db, agent_id)
    if agent is None:
        raise ComplianceAgentNotFoundError
    metrics = compliance_repository.get_agent_report_metrics(db, agent_id)

    return AgentComplianceReport(
        agent=AgentRead.model_validate(agent),
        **metrics.__dict__,
    )


def list_incidents(
    db: Session,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    severity: AgentRiskLevel | None = None,
    status: IncidentStatus | None = None,
    agent_id: UUID | None = None,
    limit: int,
    offset: int,
) -> ComplianceIncidentListResponse:
    date_range = build_date_range(start_date, end_date)
    incidents, total = compliance_repository.list_incidents(
        db,
        start_at=date_range.start_at,
        end_at=date_range.end_at,
        severity=severity,
        status=status,
        agent_id=agent_id,
        limit=limit,
        offset=offset,
    )
    return ComplianceIncidentListResponse(
        items=[incident_to_read(incident) for incident in incidents],
        total=total,
    )


def incident_to_read(incident: Incident) -> ComplianceIncidentRead:
    return ComplianceIncidentRead(
        id=incident.id,
        agent_id=incident.agent_id,
        execution_id=incident.execution_id,
        title=incident.title,
        severity=incident.severity,
        status=incident.status,
        reported_by=incident.reported_by,
        assigned_to=incident.assigned_to,
        created_at=incident.created_at,
        resolved_at=incident.resolved_at,
    )


def build_date_range(start_date: date | None, end_date: date | None) -> DateRange:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise InvalidComplianceDateRangeError

    start_at = None
    end_at = None
    if start_date is not None:
        start_at = datetime.combine(start_date, time.min, tzinfo=UTC)
    if end_date is not None:
        end_at = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)
    return DateRange(start_at=start_at, end_at=end_at)
