from uuid import UUID

from sqlalchemy.orm import Session

from app.models.agent import AgentRiskLevel, utc_now
from app.models.approval import Approval, ApprovalStatus
from app.models.audit_log import AuditAction, JsonObject
from app.repositories import agents as agent_repository
from app.repositories import approvals as approval_repository
from app.schemas.approval import ApprovalCreate, ApprovalDecision, ApprovalRead
from app.schemas.audit_log import AuditLogCreate
from app.services import audit_logs as audit_log_service


class ApprovalNotFoundError(Exception):
    pass


class InvalidApprovalTransitionError(Exception):
    pass


class ApprovalAgentNotFoundError(Exception):
    pass


def serialize_approval(approval: Approval) -> JsonObject:
    return ApprovalRead.model_validate(approval).model_dump(mode="json")


def create_approval(db: Session, approval_create: ApprovalCreate) -> Approval:
    if agent_repository.get_agent_by_id(db, approval_create.agent_id) is None:
        raise ApprovalAgentNotFoundError

    approval = approval_repository.create_approval(db, approval_create)
    audit_log_service.create_audit_log(
        db,
        AuditLogCreate(
            action=AuditAction.APPROVAL_CREATED,
            entity_type="approval",
            entity_id=approval.id,
            before=None,
            after=serialize_approval(approval),
        ),
    )
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
    return approval_repository.list_approvals(
        db,
        agent_id=agent_id,
        status=status,
        risk_level=risk_level,
        requested_by=requested_by,
        approver=approver,
    )


def get_approval_by_id(db: Session, approval_id: UUID) -> Approval:
    approval = approval_repository.get_approval_by_id(db, approval_id)
    if approval is None:
        raise ApprovalNotFoundError
    return approval


def approve_approval(db: Session, approval_id: UUID, decision: ApprovalDecision) -> Approval:
    approval = get_approval_by_id(db, approval_id)
    return decide_approval(
        db,
        approval,
        decision,
        status=ApprovalStatus.APPROVED,
        audit_action=AuditAction.APPROVAL_APPROVED,
    )


def reject_approval(db: Session, approval_id: UUID, decision: ApprovalDecision) -> Approval:
    approval = get_approval_by_id(db, approval_id)
    return decide_approval(
        db,
        approval,
        decision,
        status=ApprovalStatus.REJECTED,
        audit_action=AuditAction.APPROVAL_REJECTED,
    )


def cancel_approval(db: Session, approval_id: UUID, decision: ApprovalDecision) -> Approval:
    approval = get_approval_by_id(db, approval_id)
    return decide_approval(
        db,
        approval,
        decision,
        status=ApprovalStatus.CANCELLED,
        audit_action=AuditAction.APPROVAL_CANCELLED,
    )


def decide_approval(
    db: Session,
    approval: Approval,
    decision: ApprovalDecision,
    *,
    status: ApprovalStatus,
    audit_action: AuditAction,
) -> Approval:
    if approval.status != ApprovalStatus.PENDING:
        raise InvalidApprovalTransitionError

    before = serialize_approval(approval)
    original_values = {
        "status": approval.status,
        "approver": approval.approver,
        "decision_reason": approval.decision_reason,
        "decided_at": approval.decided_at,
    }
    approval.status = status
    approval.approver = decision.approver
    approval.decision_reason = decision.decision_reason
    approval.decided_at = utc_now()

    updated_approval = approval_repository.update_approval(db, approval)
    try:
        audit_log_service.create_critical_audit_log(
            db,
            AuditLogCreate(
                action=audit_action,
                entity_type="approval",
                entity_id=updated_approval.id,
                before=before,
                after=serialize_approval(updated_approval),
            ),
        )
    except audit_log_service.AuditLoggingError:
        for field, value in original_values.items():
            setattr(updated_approval, field, value)
        approval_repository.update_approval(db, updated_approval)
        raise
    return updated_approval
