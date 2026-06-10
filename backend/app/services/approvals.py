from uuid import UUID

from sqlalchemy.orm import Session

from app.core.security import assert_resource_in_org, log_resource_access_denied
from app.models.agent import AgentRiskLevel, utc_now
from app.models.approval import Approval, ApprovalStatus
from app.models.audit_log import AuditAction, AuditOutcome, JsonObject
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
    limit: int,
    offset: int,
) -> tuple[list[Approval], int]:
    return approval_repository.list_approvals(
        db,
        agent_id=agent_id,
        status=status,
        risk_level=risk_level,
        requested_by=requested_by,
        approver=approver,
        limit=limit,
        offset=offset,
    )


def get_approval_by_id(db: Session, approval_id: UUID) -> Approval:
    approval = approval_repository.get_approval_by_id(db, approval_id)
    if approval is None:
        log_resource_access_denied(
            db,
            attempted_action="access_approval",
            target_resource=f"approval:{approval_id}",
        )
        raise ApprovalNotFoundError
    assert_resource_in_org(db, approval, resource_name="Approval")
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
        audit_log_service.record_event(
            db,
            action=AuditAction.SECURITY_ACCESS_DENIED,
            resource_type="approval",
            resource_id=approval.id,
            outcome=AuditOutcome.DENIED,
            reason="Only pending approvals can be changed.",
            metadata={"attempted_action": audit_action.value},
        )
        raise InvalidApprovalTransitionError

    before = serialize_approval(approval)
    try:
        approval.status = status
        approval.approver = decision.approver
        approval.decision_reason = decision.decision_reason
        approval.decided_at = utc_now()

        updated_approval = approval_repository.update_approval_pending(db, approval)
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
        db.commit()
        db.refresh(updated_approval)
    except Exception:
        db.rollback()
        raise
    return updated_approval
