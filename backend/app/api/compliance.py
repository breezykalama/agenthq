from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.agent import AgentRiskLevel
from app.models.incident import IncidentStatus
from app.schemas.compliance import (
    AgentComplianceReport,
    ComplianceIncidentListResponse,
    ComplianceSummary,
)
from app.services import compliance as compliance_service

router = APIRouter(prefix="/api/v1/compliance", tags=["compliance"])
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.get("/summary", response_model=ComplianceSummary)
def get_compliance_summary(
    db: DatabaseSession,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    agent_id: Annotated[UUID | None, Query()] = None,
) -> ComplianceSummary:
    try:
        return compliance_service.get_summary(
            db,
            start_date=start_date,
            end_date=end_date,
            agent_id=agent_id,
        )
    except compliance_service.InvalidComplianceDateRangeError as exc:
        raise invalid_date_range_error() from exc


@router.get("/agent/{agent_id}", response_model=AgentComplianceReport)
def get_agent_compliance(agent_id: UUID, db: DatabaseSession) -> AgentComplianceReport:
    try:
        return compliance_service.get_agent_report(db, agent_id)
    except compliance_service.ComplianceAgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found.",
        ) from exc


@router.get("/incidents", response_model=ComplianceIncidentListResponse)
def list_compliance_incidents(
    db: DatabaseSession,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    severity: Annotated[AgentRiskLevel | None, Query()] = None,
    status: Annotated[IncidentStatus | None, Query()] = None,
    agent_id: Annotated[UUID | None, Query()] = None,
) -> ComplianceIncidentListResponse:
    try:
        return compliance_service.list_incidents(
            db,
            start_date=start_date,
            end_date=end_date,
            severity=severity,
            status=status,
            agent_id=agent_id,
        )
    except compliance_service.InvalidComplianceDateRangeError as exc:
        raise invalid_date_range_error() from exc


def invalid_date_range_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail="start_date cannot be after end_date.",
    )
