from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.pagination import PaginationParams
from app.core.security import require_roles
from app.db.session import get_db
from app.models.agent import AgentRiskLevel
from app.models.incident import IncidentStatus
from app.models.user import UserRole
from app.schemas.incident import (
    IncidentCreate,
    IncidentDecision,
    IncidentListResponse,
    IncidentRead,
    IncidentUpdate,
)
from app.services import incidents as incident_service

router = APIRouter(
    prefix="/api/v1/incidents",
    tags=["incidents"],
    dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.AUDITOR, UserRole.OPERATOR))],
)
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=IncidentRead, status_code=status.HTTP_201_CREATED)
def create_incident(incident_create: IncidentCreate, db: DatabaseSession) -> IncidentRead:
    try:
        return IncidentRead.model_validate(incident_service.create_incident(db, incident_create))
    except incident_service.IncidentAgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found.",
        ) from exc
    except incident_service.InvalidIncidentExecutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Execution must exist and belong to the agent.",
        ) from exc
    except incident_service.IncidentResolutionNotesRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Resolution notes are required when resolving an incident.",
        ) from exc


@router.get("", response_model=IncidentListResponse)
def list_incidents(
    db: DatabaseSession,
    pagination: PaginationParams,
    agent_id: Annotated[UUID | None, Query()] = None,
    execution_id: Annotated[UUID | None, Query()] = None,
    severity: Annotated[AgentRiskLevel | None, Query()] = None,
    status: Annotated[IncidentStatus | None, Query()] = None,
    reported_by: Annotated[str | None, Query()] = None,
    assigned_to: Annotated[str | None, Query()] = None,
) -> IncidentListResponse:
    incidents, total = incident_service.list_incidents(
        db,
        agent_id=agent_id,
        execution_id=execution_id,
        severity=severity,
        status=status,
        reported_by=reported_by,
        assigned_to=assigned_to,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    return IncidentListResponse(
        items=[IncidentRead.model_validate(incident) for incident in incidents],
        total=total,
    )


@router.get("/{incident_id}", response_model=IncidentRead)
def get_incident(incident_id: UUID, db: DatabaseSession) -> IncidentRead:
    try:
        return IncidentRead.model_validate(incident_service.get_incident_by_id(db, incident_id))
    except incident_service.IncidentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Incident not found.",
        ) from exc


@router.patch("/{incident_id}", response_model=IncidentRead)
def update_incident(
    incident_id: UUID,
    incident_update: IncidentUpdate,
    db: DatabaseSession,
) -> IncidentRead:
    try:
        return IncidentRead.model_validate(
            incident_service.update_incident(db, incident_id, incident_update)
        )
    except incident_service.IncidentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Incident not found.",
        ) from exc
    except incident_service.InvalidIncidentTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Incident status transition is not allowed.",
        ) from exc
    except incident_service.IncidentResolutionNotesRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Resolution notes are required when resolving an incident.",
        ) from exc


@router.post("/{incident_id}/resolve", response_model=IncidentRead)
def resolve_incident(
    incident_id: UUID,
    db: DatabaseSession,
    decision: Annotated[IncidentDecision | None, Body()] = None,
) -> IncidentRead:
    try:
        return IncidentRead.model_validate(
            incident_service.resolve_incident(db, incident_id, decision or IncidentDecision())
        )
    except incident_service.IncidentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Incident not found.",
        ) from exc
    except incident_service.InvalidIncidentTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Incident status transition is not allowed.",
        ) from exc
    except incident_service.IncidentResolutionNotesRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Resolution notes are required when resolving an incident.",
        ) from exc


@router.post("/{incident_id}/dismiss", response_model=IncidentRead)
def dismiss_incident(
    incident_id: UUID,
    db: DatabaseSession,
    decision: Annotated[IncidentDecision | None, Body()] = None,
) -> IncidentRead:
    try:
        return IncidentRead.model_validate(
            incident_service.dismiss_incident(db, incident_id, decision or IncidentDecision())
        )
    except incident_service.IncidentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Incident not found.",
        ) from exc
    except incident_service.InvalidIncidentTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Incident status transition is not allowed.",
        ) from exc
