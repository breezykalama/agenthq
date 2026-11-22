from collections.abc import Collection
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.orm import Session

from app.core.tenancy import get_current_organization_id
from app.models.agent import AgentRiskLevel
from app.models.approval import Approval, ApprovalStatus
from app.schemas.approval import ApprovalCreate


def create_approval(db: Session, approval_create: ApprovalCreate) -> Approval:
    approval = Approval(
        organization_id=get_current_organization_id(db),
        **approval_create.model_dump(),
        status=ApprovalStatus.PENDING,
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)
    return approval


def list_approvals(
    db: Session,
    *,
    agent_id: UUID | None = None,
    status: ApprovalStatus | None = None,
    risk_level: AgentRiskLevel | None = None,
    requested_by: str | None = None,
    approver: str | None = None,
    limit: int,
    offset: int,
) -> tuple[list[Approval], int]:
    filters = [Approval.organization_id == get_current_organization_id(db)]
    if agent_id is not None:
        filters.append(Approval.agent_id == agent_id)
    if status is not None:
        filters.append(Approval.status == status)
    if risk_level is not None:
        filters.append(Approval.risk_level == risk_level)
    if requested_by is not None:
        filters.append(Approval.requested_by == requested_by)
    if approver is not None:
        filters.append(Approval.approver == approver)

    statement = (
        select(Approval)
        .where(*filters)
        .order_by(Approval.requested_at.desc())
        .limit(limit)
        .offset(offset)
    )
    count_statement = select(func.count()).select_from(Approval).where(*filters)

    approvals = list(db.scalars(statement).all())
    total = db.scalar(count_statement) or 0
    return approvals, total


def get_approval_by_id(db: Session, approval_id: UUID) -> Approval | None:
    statement = select(Approval).where(
        Approval.organization_id == get_current_organization_id(db),
        Approval.id == approval_id,
    )
    return db.scalar(statement)


def update_approval(db: Session, approval: Approval) -> Approval:
    db.add(approval)
    db.commit()
    db.refresh(approval)
    return approval


def update_approval_pending(db: Session, approval: Approval) -> Approval:
    db.add(approval)
    db.flush()
    return approval


def claim_approval_pending(
    db: Session,
    approval_id: UUID,
    *,
    agent_id: UUID,
    requested_action: str,
    allowed_risk_levels: Collection[AgentRiskLevel],
    execution_id: UUID,
    consumed_at: datetime,
) -> bool:
    """Atomically consume an approved, unused approval for one execution attempt.

    Every condition is re-evaluated inside one conditional UPDATE. Under PostgreSQL row locking a
    concurrent claim waits for the first and then sees ``consumed_at`` set, so at most one
    request can succeed. The caller commits.
    """
    if not allowed_risk_levels:
        return False
    statement = (
        update(Approval)
        .where(
            Approval.id == approval_id,
            Approval.organization_id == get_current_organization_id(db),
            Approval.agent_id == agent_id,
            Approval.requested_action == requested_action,
            Approval.status == ApprovalStatus.APPROVED,
            Approval.consumed_at.is_(None),
            Approval.risk_level.in_(list(allowed_risk_levels)),
        )
        .values(consumed_at=consumed_at, consumed_by_execution_id=execution_id)
        .execution_options(synchronize_session=False)
    )
    result = cast(CursorResult[Any], db.execute(statement))
    return result.rowcount == 1
