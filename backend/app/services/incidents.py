from uuid import UUID

from sqlalchemy.orm import Session

from app.core.security import assert_resource_in_org, log_resource_access_denied
from app.models.agent import AgentRiskLevel, utc_now
from app.models.audit_log import AuditAction, JsonObject
from app.models.incident import Incident, IncidentStatus
from app.repositories import agents as agent_repository
from app.repositories import executions as execution_repository
from app.repositories import incidents as incident_repository
from app.schemas.audit_log import AuditLogCreate
from app.schemas.incident import IncidentCreate, IncidentDecision, IncidentRead, IncidentUpdate
from app.services import audit_logs as audit_log_service

ACTIVE_STATUSES = {IncidentStatus.OPEN, IncidentStatus.INVESTIGATING}
CLOSED_STATUSES = {IncidentStatus.RESOLVED, IncidentStatus.DISMISSED}


class IncidentNotFoundError(Exception):
    pass


class IncidentAgentNotFoundError(Exception):
    pass


class InvalidIncidentExecutionError(Exception):
    pass


class InvalidIncidentTransitionError(Exception):
    pass


class IncidentResolutionNotesRequiredError(Exception):
    pass


def serialize_incident(incident: Incident) -> JsonObject:
    return IncidentRead.model_validate(incident).model_dump(mode="json")


def create_incident(db: Session, incident_create: IncidentCreate) -> Incident:
    validate_agent_and_execution(db, incident_create.agent_id, incident_create.execution_id)

    values = incident_create
    if values.status in CLOSED_STATUSES:
        if values.status == IncidentStatus.RESOLVED and not values.resolution_notes:
            raise IncidentResolutionNotesRequiredError

    incident = incident_repository.create_incident(db, values)
    if incident.status in CLOSED_STATUSES and incident.resolved_at is None:
        incident = incident_repository.update_incident(db, incident, {"resolved_at": utc_now()})

    audit_incident(db, AuditAction.INCIDENT_CREATED, incident, before=None)
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
    return incident_repository.list_incidents(
        db,
        agent_id=agent_id,
        execution_id=execution_id,
        severity=severity,
        status=status,
        reported_by=reported_by,
        assigned_to=assigned_to,
        limit=limit,
        offset=offset,
    )


def get_incident_by_id(db: Session, incident_id: UUID) -> Incident:
    incident = incident_repository.get_incident_by_id(db, incident_id)
    if incident is None:
        log_resource_access_denied(
            db,
            attempted_action="access_incident",
            target_resource=f"incident:{incident_id}",
        )
        raise IncidentNotFoundError
    assert_resource_in_org(db, incident, resource_name="Incident")
    return incident


def update_incident(
    db: Session,
    incident_id: UUID,
    incident_update: IncidentUpdate,
) -> Incident:
    incident = get_incident_by_id(db, incident_id)
    before = serialize_incident(incident)
    values = incident_update.model_dump(exclude_unset=True)

    if incident.status in CLOSED_STATUSES:
        new_status = values.get("status")
        if new_status in {IncidentStatus.OPEN, IncidentStatus.INVESTIGATING}:
            raise InvalidIncidentTransitionError

    new_status = values.get("status")
    if isinstance(new_status, IncidentStatus) and new_status in CLOSED_STATUSES:
        if incident.status not in ACTIVE_STATUSES:
            raise InvalidIncidentTransitionError
        if new_status == IncidentStatus.RESOLVED and not values.get("resolution_notes"):
            raise IncidentResolutionNotesRequiredError
        values["resolved_at"] = utc_now()

    updated_incident = incident_repository.update_incident(db, incident, values)
    audit_incident(db, AuditAction.INCIDENT_UPDATED, updated_incident, before=before)
    return updated_incident


def resolve_incident(
    db: Session,
    incident_id: UUID,
    decision: IncidentDecision,
) -> Incident:
    if not decision.resolution_notes:
        raise IncidentResolutionNotesRequiredError
    return decide_incident(
        db,
        incident_id,
        status=IncidentStatus.RESOLVED,
        resolution_notes=decision.resolution_notes,
        audit_action=AuditAction.INCIDENT_RESOLVED,
    )


def dismiss_incident(
    db: Session,
    incident_id: UUID,
    decision: IncidentDecision,
) -> Incident:
    return decide_incident(
        db,
        incident_id,
        status=IncidentStatus.DISMISSED,
        resolution_notes=decision.resolution_notes,
        audit_action=AuditAction.INCIDENT_DISMISSED,
    )


def decide_incident(
    db: Session,
    incident_id: UUID,
    *,
    status: IncidentStatus,
    resolution_notes: str | None,
    audit_action: AuditAction,
) -> Incident:
    incident = get_incident_by_id(db, incident_id)
    if incident.status not in ACTIVE_STATUSES:
        raise InvalidIncidentTransitionError

    before = serialize_incident(incident)
    updated_incident = incident_repository.update_incident(
        db,
        incident,
        {
            "status": status,
            "resolution_notes": resolution_notes,
            "resolved_at": utc_now(),
        },
    )
    audit_incident(db, audit_action, updated_incident, before=before)
    return updated_incident


def validate_agent_and_execution(
    db: Session,
    agent_id: UUID,
    execution_id: UUID | None,
) -> None:
    if agent_repository.get_agent_by_id(db, agent_id) is None:
        raise IncidentAgentNotFoundError

    if execution_id is None:
        return

    execution = execution_repository.get_execution_by_id(db, execution_id)
    if execution is None or execution.agent_id != agent_id:
        raise InvalidIncidentExecutionError


def audit_incident(
    db: Session,
    action: AuditAction,
    incident: Incident,
    *,
    before: JsonObject | None,
) -> None:
    audit_log_service.create_audit_log(
        db,
        AuditLogCreate(
            action=action,
            entity_type="incident",
            entity_id=incident.id,
            before=before,
            after=serialize_incident(incident),
        ),
    )
