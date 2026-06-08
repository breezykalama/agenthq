from uuid import UUID

from sqlalchemy.orm import Session

from app.models.agent import AgentRiskLevel, utc_now
from app.models.approval import ApprovalStatus
from app.models.audit_log import AuditAction, JsonObject
from app.models.execution import Execution, ExecutionStatus
from app.models.policy_rule import PolicyRuleEffect
from app.repositories import agents as agent_repository
from app.repositories import approvals as approval_repository
from app.repositories import executions as execution_repository
from app.schemas.audit_log import AuditLogCreate
from app.schemas.execution import ExecutionCreate, ExecutionRead, ExecutionUpdate
from app.schemas.policy_decision import PolicyDecisionRequest, PolicyDecisionResponse
from app.services import audit_logs as audit_log_service
from app.services import policy_decisions as policy_decision_service

TERMINAL_STATUSES = {
    ExecutionStatus.SUCCEEDED,
    ExecutionStatus.FAILED,
    ExecutionStatus.BLOCKED,
}
APPROVAL_REQUIRED_RISK_LEVELS = {
    AgentRiskLevel.HIGH,
    AgentRiskLevel.CRITICAL,
}


class ExecutionNotFoundError(Exception):
    pass


class ExecutionAgentNotFoundError(Exception):
    pass


class InvalidExecutionApprovalError(Exception):
    pass


class ExecutionToolNotFoundError(Exception):
    pass


class ExecutionToolDisabledError(Exception):
    pass


def serialize_execution(execution: Execution) -> JsonObject:
    return ExecutionRead.model_validate(execution).model_dump(mode="json")


def create_execution(db: Session, execution_create: ExecutionCreate) -> Execution:
    try:
        if agent_repository.get_agent_by_id(db, execution_create.agent_id) is None:
            raise ExecutionAgentNotFoundError

        policy_decision = evaluate_policy_decision(db, execution_create)
        values = execution_create.model_dump(exclude_none=True)
        status = execution_create.status or ExecutionStatus.PENDING

        if execution_create.approval_id is not None:
            validate_approval(db, execution_create.agent_id, execution_create.approval_id)

        if policy_decision.decision == PolicyRuleEffect.BLOCK:
            status = ExecutionStatus.BLOCKED
        elif (
            policy_decision.decision == PolicyRuleEffect.REQUIRE_APPROVAL
            and execution_create.approval_id is None
        ):
            status = ExecutionStatus.REQUIRES_APPROVAL

        values["status"] = status
        values["policy_decision"] = policy_decision.decision
        values["policy_decision_reason"] = policy_decision.reason
        values["policy_rule_id"] = policy_decision.matched_rule_id
        if status in TERMINAL_STATUSES:
            values["completed_at"] = utc_now()

        execution = execution_repository.create_execution_pending(db, values)
        audit_log_service.create_critical_audit_log(
            db,
            AuditLogCreate(
                action=AuditAction.EXECUTION_CREATED,
                entity_type="execution",
                entity_id=execution.id,
                before=None,
                after=serialize_execution(execution),
            ),
        )
        db.commit()
        db.refresh(execution)
    except Exception:
        db.rollback()
        raise
    return execution


def evaluate_policy_decision(
    db: Session,
    execution_create: ExecutionCreate,
) -> PolicyDecisionResponse:
    try:
        return policy_decision_service.evaluate_policy_decision(
            db,
            PolicyDecisionRequest(
                agent_id=execution_create.agent_id,
                tool_id=execution_create.tool_id,
                requested_action=execution_create.action_name,
                risk_level=execution_create.risk_level,
            ),
            commit=False,
        )
    except policy_decision_service.PolicyDecisionAgentNotFoundError as exc:
        raise ExecutionAgentNotFoundError from exc
    except policy_decision_service.PolicyDecisionToolNotFoundError as exc:
        raise ExecutionToolNotFoundError from exc
    except policy_decision_service.PolicyDecisionToolDisabledError as exc:
        raise ExecutionToolDisabledError from exc
    except audit_log_service.AuditLoggingError:
        raise
    except Exception:
        fallback = PolicyDecisionResponse(
            decision=PolicyRuleEffect.BLOCK,
            matched_rule_id=None,
            matched_rule_name=None,
            reason=(
                "Policy evaluation failed unexpectedly; fail-closed fallback blocked the execution."
            ),
            requires_approval=False,
        )
        policy_decision_service.audit_decision(
            db,
            PolicyDecisionRequest(
                agent_id=execution_create.agent_id,
                tool_id=execution_create.tool_id,
                requested_action=execution_create.action_name,
                risk_level=execution_create.risk_level,
            ),
            fallback,
        )
        return fallback


def list_executions(
    db: Session,
    *,
    agent_id: UUID | None = None,
    status: ExecutionStatus | None = None,
    risk_level: AgentRiskLevel | None = None,
    approval_id: UUID | None = None,
    limit: int,
    offset: int,
) -> tuple[list[Execution], int]:
    return execution_repository.list_executions(
        db,
        agent_id=agent_id,
        status=status,
        risk_level=risk_level,
        approval_id=approval_id,
        limit=limit,
        offset=offset,
    )


def get_execution_by_id(db: Session, execution_id: UUID) -> Execution:
    execution = execution_repository.get_execution_by_id(db, execution_id)
    if execution is None:
        raise ExecutionNotFoundError
    return execution


def update_execution(
    db: Session,
    execution_id: UUID,
    execution_update: ExecutionUpdate,
) -> Execution:
    execution = get_execution_by_id(db, execution_id)
    before = serialize_execution(execution)
    values = execution_update.model_dump(exclude_unset=True)

    approval_id = values.get("approval_id")
    if isinstance(approval_id, UUID):
        validate_approval(db, execution.agent_id, approval_id)

    status = values.get("status")
    if isinstance(status, ExecutionStatus) and status in TERMINAL_STATUSES:
        values.setdefault("completed_at", utc_now())

    updated_execution = execution_repository.update_execution(db, execution, values)
    audit_log_service.create_audit_log(
        db,
        AuditLogCreate(
            action=AuditAction.EXECUTION_UPDATED,
            entity_type="execution",
            entity_id=updated_execution.id,
            before=before,
            after=serialize_execution(updated_execution),
        ),
    )
    return updated_execution


def validate_approval(db: Session, agent_id: UUID, approval_id: UUID) -> None:
    approval = approval_repository.get_approval_by_id(db, approval_id)
    if (
        approval is None
        or approval.agent_id != agent_id
        or approval.status != ApprovalStatus.APPROVED
    ):
        raise InvalidExecutionApprovalError
