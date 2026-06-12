from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.pagination import PaginationParams
from app.core.security import OrgPermission, require_current_organization, require_org_permission
from app.db.session import get_db
from app.models.agent import AgentRiskLevel
from app.schemas.agent_tool import AgentToolReview
from app.schemas.tool_governance import (
    ToolGovernanceListResponse,
    ToolGovernanceRead,
    ToolGovernanceStatus,
    ToolGovernanceSummary,
)
from app.services import tool_governance as governance_service

router = APIRouter(
    prefix="/api/v1/tool-governance",
    tags=["tool-governance"],
    dependencies=[
        Depends(require_current_organization),
        Depends(require_org_permission(OrgPermission.VIEW_DASHBOARD)),
    ],
)
summary_router = APIRouter(
    prefix="/api/v1",
    tags=["tool-governance"],
    dependencies=[
        Depends(require_current_organization),
        Depends(require_org_permission(OrgPermission.VIEW_DASHBOARD)),
    ],
)
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.get("", response_model=ToolGovernanceListResponse)
def list_tool_governance(
    db: DatabaseSession,
    pagination: PaginationParams,
    governance_status: Annotated[ToolGovernanceStatus | None, Query()] = None,
    risk_level: Annotated[AgentRiskLevel | None, Query()] = None,
    mcp_server_id: Annotated[UUID | None, Query()] = None,
    agent_id: Annotated[UUID | None, Query()] = None,
) -> ToolGovernanceListResponse:
    items, total = governance_service.list_tools(
        db,
        governance_status_filter=governance_status,
        risk_level=risk_level,
        server_id=mcp_server_id,
        agent_id=agent_id,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    return ToolGovernanceListResponse(items=items, total=total)


@router.get("/{tool_id}", response_model=ToolGovernanceRead)
def get_tool_governance(tool_id: UUID, db: DatabaseSession) -> ToolGovernanceRead:
    try:
        return governance_service.get_tool(db, tool_id)
    except governance_service.DiscoveredToolNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Discovered tool not found.",
        ) from exc


@router.post(
    "/{tool_id}/review",
    response_model=ToolGovernanceRead,
    dependencies=[Depends(require_org_permission(OrgPermission.REVIEW_TOOLS))],
)
def review_tool_governance(
    tool_id: UUID,
    review: AgentToolReview,
    db: DatabaseSession,
) -> ToolGovernanceRead:
    try:
        return governance_service.review_tool(db, tool_id, review)
    except governance_service.DiscoveredToolNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Discovered tool not found.",
        ) from exc


@summary_router.get("/tool-governance-summary", response_model=ToolGovernanceSummary)
def get_tool_governance_summary(db: DatabaseSession) -> ToolGovernanceSummary:
    return governance_service.get_summary(db)
