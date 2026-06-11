from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.pagination import PaginationParams
from app.core.rate_limit import enforce_authenticated_rate_limit
from app.core.security import OrgPermission, require_current_organization, require_org_permission
from app.db.session import get_db
from app.models.agent import AgentRiskLevel
from app.models.approval import ApprovalStatus
from app.schemas.approval import (
    ApprovalCreate,
    ApprovalDecision,
    ApprovalListResponse,
    ApprovalRead,
)
from app.services import approvals as approval_service

router = APIRouter(
    prefix="/api/v1/approvals",
    tags=["approvals"],
    dependencies=[
        Depends(require_current_organization),
        Depends(require_org_permission(OrgPermission.MANAGE_APPROVALS)),
    ],
)
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=ApprovalRead, status_code=status.HTTP_201_CREATED)
def create_approval(
    approval_create: ApprovalCreate,
    request: Request,
    db: DatabaseSession,
) -> ApprovalRead:
    enforce_authenticated_rate_limit(
        request,
        db,
        "approval_action",
        resource_type="approval",
    )
    try:
        return ApprovalRead.model_validate(approval_service.create_approval(db, approval_create))
    except approval_service.ApprovalAgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found.",
        ) from exc


@router.get("", response_model=ApprovalListResponse)
def list_approvals(
    db: DatabaseSession,
    pagination: PaginationParams,
    agent_id: Annotated[UUID | None, Query()] = None,
    status: Annotated[ApprovalStatus | None, Query()] = None,
    risk_level: Annotated[AgentRiskLevel | None, Query()] = None,
    requested_by: Annotated[str | None, Query()] = None,
    approver: Annotated[str | None, Query()] = None,
) -> ApprovalListResponse:
    approvals, total = approval_service.list_approvals(
        db,
        agent_id=agent_id,
        status=status,
        risk_level=risk_level,
        requested_by=requested_by,
        approver=approver,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    return ApprovalListResponse(
        items=[ApprovalRead.model_validate(approval) for approval in approvals],
        total=total,
    )


@router.get("/{approval_id}", response_model=ApprovalRead)
def get_approval(approval_id: UUID, db: DatabaseSession) -> ApprovalRead:
    try:
        return ApprovalRead.model_validate(approval_service.get_approval_by_id(db, approval_id))
    except approval_service.ApprovalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval not found.",
        ) from exc


@router.post("/{approval_id}/approve", response_model=ApprovalRead)
def approve_approval(
    approval_id: UUID,
    request: Request,
    db: DatabaseSession,
    decision: Annotated[ApprovalDecision | None, Body()] = None,
) -> ApprovalRead:
    enforce_authenticated_rate_limit(
        request,
        db,
        "approval_action",
        resource_type="approval",
        resource_id=approval_id,
    )
    try:
        return ApprovalRead.model_validate(
            approval_service.approve_approval(db, approval_id, decision or ApprovalDecision())
        )
    except approval_service.ApprovalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval not found.",
        ) from exc
    except approval_service.InvalidApprovalTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending approvals can be changed.",
        ) from exc


@router.post("/{approval_id}/reject", response_model=ApprovalRead)
def reject_approval(
    approval_id: UUID,
    request: Request,
    db: DatabaseSession,
    decision: Annotated[ApprovalDecision | None, Body()] = None,
) -> ApprovalRead:
    enforce_authenticated_rate_limit(
        request,
        db,
        "approval_action",
        resource_type="approval",
        resource_id=approval_id,
    )
    try:
        return ApprovalRead.model_validate(
            approval_service.reject_approval(db, approval_id, decision or ApprovalDecision())
        )
    except approval_service.ApprovalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval not found.",
        ) from exc
    except approval_service.InvalidApprovalTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending approvals can be changed.",
        ) from exc


@router.post("/{approval_id}/cancel", response_model=ApprovalRead)
def cancel_approval(
    approval_id: UUID,
    request: Request,
    db: DatabaseSession,
    decision: Annotated[ApprovalDecision | None, Body()] = None,
) -> ApprovalRead:
    enforce_authenticated_rate_limit(
        request,
        db,
        "approval_action",
        resource_type="approval",
        resource_id=approval_id,
    )
    try:
        return ApprovalRead.model_validate(
            approval_service.cancel_approval(db, approval_id, decision or ApprovalDecision())
        )
    except approval_service.ApprovalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval not found.",
        ) from exc
    except approval_service.InvalidApprovalTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending approvals can be changed.",
        ) from exc
