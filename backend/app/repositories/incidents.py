from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agent import AgentRiskLevel
from app.models.incident import Incident, IncidentStatus
from app.schemas.incident import IncidentCreate


def create_incident(db: Session, incident_create: IncidentCreate) -> Incident:
    incident = Incident(**incident_create.model_dump())
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return incident


def list_incidents(
    db: Session,
    *,
    agent_id: UUID | None = None,
    execution_id: UUID | None = None,
    severity: AgentRiskLevel | None = None,
    status: IncidentStatus | None = None,
    reported_by: str | None = None,
    assigned_to: str | None = None,
    limit: int,
    offset: int,
) -> tuple[list[Incident], int]:
    filters = []
    if agent_id is not None:
        filters.append(Incident.agent_id == agent_id)
    if execution_id is not None:
        filters.append(Incident.execution_id == execution_id)
    if severity is not None:
        filters.append(Incident.severity == severity)
    if status is not None:
        filters.append(Incident.status == status)
    if reported_by is not None:
        filters.append(Incident.reported_by == reported_by)
    if assigned_to is not None:
        filters.append(Incident.assigned_to == assigned_to)

    statement = (
        select(Incident)
        .where(*filters)
        .order_by(Incident.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    count_statement = select(func.count()).select_from(Incident).where(*filters)

    incidents = list(db.scalars(statement).all())
    total = db.scalar(count_statement) or 0
    return incidents, total


def get_incident_by_id(db: Session, incident_id: UUID) -> Incident | None:
    statement = select(Incident).where(Incident.id == incident_id)
    return db.scalar(statement)


def update_incident(db: Session, incident: Incident, values: dict[str, object]) -> Incident:
    for field, value in values.items():
        setattr(incident, field, value)

    db.add(incident)
    db.commit()
    db.refresh(incident)
    return incident
