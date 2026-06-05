from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agent import AgentRiskLevel
from app.models.approval import Approval, ApprovalStatus
from app.schemas.approval import ApprovalCreate


def create_approval(db: Session, approval_create: ApprovalCreate) -> Approval:
    approval = Approval(**approval_create.model_dump(), status=ApprovalStatus.PENDING)
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
) -> tuple[list[Approval], int]:
    filters = []
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

    statement = select(Approval).where(*filters).order_by(Approval.requested_at.desc())
    count_statement = select(func.count()).select_from(Approval).where(*filters)

    approvals = list(db.scalars(statement).all())
    total = db.scalar(count_statement) or 0
    return approvals, total


def get_approval_by_id(db: Session, approval_id: UUID) -> Approval | None:
    statement = select(Approval).where(Approval.id == approval_id)
    return db.scalar(statement)


def update_approval(db: Session, approval: Approval) -> Approval:
    db.add(approval)
    db.commit()
    db.refresh(approval)
    return approval
