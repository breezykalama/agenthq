from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import OrgPermission, require_current_organization, require_org_permission
from app.db.session import get_db
from app.schemas.dashboard import (
    AgentsByRisk,
    ApprovalsByStatus,
    DashboardSummary,
    ExecutionsByStatus,
)
from app.services import dashboard as dashboard_service

router = APIRouter(
    prefix="/api/v1/dashboard",
    tags=["dashboard"],
    dependencies=[
        Depends(require_current_organization),
        Depends(require_org_permission(OrgPermission.VIEW_DASHBOARD)),
    ],
)
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.get("/summary", response_model=DashboardSummary)
def get_summary(db: DatabaseSession) -> DashboardSummary:
    return dashboard_service.get_summary(db)


@router.get("/agents-by-risk", response_model=AgentsByRisk)
def get_agents_by_risk(db: DatabaseSession) -> AgentsByRisk:
    return dashboard_service.get_agents_by_risk(db)


@router.get("/executions-by-status", response_model=ExecutionsByStatus)
def get_executions_by_status(db: DatabaseSession) -> ExecutionsByStatus:
    return dashboard_service.get_executions_by_status(db)


@router.get("/approvals-by-status", response_model=ApprovalsByStatus)
def get_approvals_by_status(db: DatabaseSession) -> ApprovalsByStatus:
    return dashboard_service.get_approvals_by_status(db)
