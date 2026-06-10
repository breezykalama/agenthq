from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.pagination import PaginationParams
from app.core.security import OrgPermission, require_current_organization, require_org_permission
from app.db.session import get_db
from app.models.agent import AgentRiskLevel
from app.models.execution import ExecutionStatus
from app.schemas.execution import (
    ExecutionCreate,
    ExecutionListResponse,
    ExecutionRead,
    ExecutionUpdate,
)
from app.services import executions as execution_service

router = APIRouter(
    prefix="/api/v1/executions",
    tags=["executions"],
    dependencies=[
        Depends(require_current_organization),
        Depends(require_org_permission(OrgPermission.MANAGE_EXECUTIONS)),
    ],
)
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=ExecutionRead, status_code=status.HTTP_201_CREATED)
def create_execution(execution_create: ExecutionCreate, db: DatabaseSession) -> ExecutionRead:
    try:
        return ExecutionRead.model_validate(
            execution_service.create_execution(db, execution_create)
        )
    except execution_service.ExecutionAgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found.",
        ) from exc
    except execution_service.InvalidExecutionApprovalError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Approval must exist, belong to the agent, and be approved.",
        ) from exc
    except execution_service.ExecutionToolNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tool not found.",
        ) from exc
    except execution_service.ExecutionToolDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tool is disabled.",
        ) from exc


@router.get("", response_model=ExecutionListResponse)
def list_executions(
    db: DatabaseSession,
    pagination: PaginationParams,
    agent_id: Annotated[UUID | None, Query()] = None,
    status: Annotated[ExecutionStatus | None, Query()] = None,
    risk_level: Annotated[AgentRiskLevel | None, Query()] = None,
    approval_id: Annotated[UUID | None, Query()] = None,
) -> ExecutionListResponse:
    executions, total = execution_service.list_executions(
        db,
        agent_id=agent_id,
        status=status,
        risk_level=risk_level,
        approval_id=approval_id,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    return ExecutionListResponse(
        items=[ExecutionRead.model_validate(execution) for execution in executions],
        total=total,
    )


@router.get("/{execution_id}", response_model=ExecutionRead)
def get_execution(execution_id: UUID, db: DatabaseSession) -> ExecutionRead:
    try:
        return ExecutionRead.model_validate(execution_service.get_execution_by_id(db, execution_id))
    except execution_service.ExecutionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution not found.",
        ) from exc


@router.patch("/{execution_id}", response_model=ExecutionRead)
def update_execution(
    execution_id: UUID,
    execution_update: ExecutionUpdate,
    db: DatabaseSession,
) -> ExecutionRead:
    try:
        return ExecutionRead.model_validate(
            execution_service.update_execution(db, execution_id, execution_update)
        )
    except execution_service.ExecutionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution not found.",
        ) from exc
    except execution_service.InvalidExecutionApprovalError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Approval must exist, belong to the agent, and be approved.",
        ) from exc
