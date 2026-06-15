from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.pagination import PaginationParams
from app.core.rate_limit import enforce_authenticated_rate_limit
from app.core.security import OrgPermission, require_current_organization, require_org_permission
from app.db.session import get_db
from app.models.agent import AgentRiskLevel
from app.models.risk_compliance import ComplianceStatus, PolicyCoverageStatus
from app.schemas.risk_compliance import (
    ComplianceControlRead,
    ComplianceEvaluation,
    RiskRegisterListResponse,
    RiskSummary,
)
from app.schemas.tool_governance import ToolGovernanceStatus
from app.services import risk_compliance as risk_service

router = APIRouter(
    prefix="/api/v1",
    tags=["risk-compliance"],
    dependencies=[
        Depends(require_current_organization),
        Depends(require_org_permission(OrgPermission.VIEW_COMPLIANCE)),
    ],
)
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.get("/risk-register", response_model=RiskRegisterListResponse)
def list_risk_register(
    request: Request,
    db: DatabaseSession,
    pagination: PaginationParams,
    risk_level: Annotated[AgentRiskLevel | None, Query()] = None,
    compliance_status: Annotated[ComplianceStatus | None, Query()] = None,
    governance_status: Annotated[ToolGovernanceStatus | None, Query()] = None,
    policy_coverage_status: Annotated[PolicyCoverageStatus | None, Query()] = None,
) -> RiskRegisterListResponse:
    enforce_authenticated_rate_limit(
        request,
        db,
        "compliance_access",
        resource_type="risk_register",
    )
    return risk_service.list_risk_register(
        db,
        risk_level=risk_level,
        compliance_status=compliance_status,
        governance_status=governance_status,
        policy_coverage_status=policy_coverage_status,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get("/compliance-controls", response_model=list[ComplianceControlRead])
def list_compliance_controls(
    request: Request,
    db: DatabaseSession,
) -> list[ComplianceControlRead]:
    enforce_authenticated_rate_limit(
        request,
        db,
        "compliance_access",
        resource_type="compliance_controls",
    )
    return risk_service.list_controls(db)


@router.get("/compliance-evaluation", response_model=ComplianceEvaluation)
def get_compliance_evaluation(
    request: Request,
    db: DatabaseSession,
    agent_id: Annotated[UUID | None, Query()] = None,
    mcp_server_id: Annotated[UUID | None, Query()] = None,
    tool_id: Annotated[UUID | None, Query()] = None,
) -> ComplianceEvaluation:
    enforce_authenticated_rate_limit(
        request,
        db,
        "compliance_access",
        resource_type="compliance_evaluation",
    )
    return risk_service.evaluate_compliance(
        db,
        agent_id=agent_id,
        mcp_server_id=mcp_server_id,
        tool_id=tool_id,
    )


@router.get("/risk-summary", response_model=RiskSummary)
def get_risk_summary(request: Request, db: DatabaseSession) -> RiskSummary:
    enforce_authenticated_rate_limit(
        request,
        db,
        "compliance_access",
        resource_type="risk_summary",
    )
    return risk_service.get_summary(db)
