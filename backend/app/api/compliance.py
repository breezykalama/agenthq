from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.pagination import PaginationParams
from app.core.rate_limit import enforce_authenticated_rate_limit
from app.core.security import OrgPermission, require_current_organization, require_org_permission
from app.db.session import get_db
from app.models.agent import AgentRiskLevel
from app.models.audit_log import AuditAction
from app.models.incident import IncidentStatus
from app.schemas.compliance import (
    AgentComplianceReport,
    ComplianceIncidentListResponse,
    ComplianceSummary,
)
from app.services import audit_logs as audit_log_service
from app.services import compliance as compliance_service

router = APIRouter(
    prefix="/api/v1/compliance",
    tags=["compliance"],
    dependencies=[
        Depends(require_current_organization),
        Depends(require_org_permission(OrgPermission.VIEW_COMPLIANCE)),
    ],
)
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.get("/summary", response_model=ComplianceSummary)
def get_compliance_summary(
    request: Request,
    db: DatabaseSession,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    agent_id: Annotated[UUID | None, Query()] = None,
) -> ComplianceSummary:
    enforce_authenticated_rate_limit(
        request,
        db,
        "compliance_access",
        resource_type="compliance_summary",
    )
    try:
        result = compliance_service.get_summary(
            db,
            start_date=start_date,
            end_date=end_date,
            agent_id=agent_id,
        )
        audit_log_service.record_event(
            db,
            action=AuditAction.COMPLIANCE_REPORT_ACCESSED,
            resource_type="compliance_summary",
            metadata={
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
                "agent_id": str(agent_id) if agent_id else None,
            },
        )
        return result
    except compliance_service.InvalidComplianceDateRangeError as exc:
        raise invalid_date_range_error() from exc


@router.get("/agent/{agent_id}", response_model=AgentComplianceReport)
def get_agent_compliance(
    agent_id: UUID,
    request: Request,
    db: DatabaseSession,
) -> AgentComplianceReport:
    enforce_authenticated_rate_limit(
        request,
        db,
        "compliance_access",
        resource_type="agent_compliance_report",
        resource_id=agent_id,
    )
    try:
        result = compliance_service.get_agent_report(db, agent_id)
        audit_log_service.record_event(
            db,
            action=AuditAction.COMPLIANCE_REPORT_ACCESSED,
            resource_type="agent_compliance_report",
            resource_id=agent_id,
        )
        return result
    except compliance_service.ComplianceAgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found.",
        ) from exc


@router.get("/incidents", response_model=ComplianceIncidentListResponse)
def list_compliance_incidents(
    request: Request,
    db: DatabaseSession,
    pagination: PaginationParams,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    severity: Annotated[AgentRiskLevel | None, Query()] = None,
    status: Annotated[IncidentStatus | None, Query()] = None,
    agent_id: Annotated[UUID | None, Query()] = None,
) -> ComplianceIncidentListResponse:
    enforce_authenticated_rate_limit(
        request,
        db,
        "compliance_access",
        resource_type="compliance_incidents",
    )
    try:
        result = compliance_service.list_incidents(
            db,
            start_date=start_date,
            end_date=end_date,
            severity=severity,
            status=status,
            agent_id=agent_id,
            limit=pagination.limit,
            offset=pagination.offset,
        )
        audit_log_service.record_event(
            db,
            action=AuditAction.COMPLIANCE_REPORT_ACCESSED,
            resource_type="compliance_incidents",
            metadata={
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
                "severity": severity.value if severity else None,
                "status": status.value if status else None,
                "agent_id": str(agent_id) if agent_id else None,
            },
        )
        return result
    except compliance_service.InvalidComplianceDateRangeError as exc:
        raise invalid_date_range_error() from exc


def invalid_date_range_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail="start_date cannot be after end_date.",
    )
