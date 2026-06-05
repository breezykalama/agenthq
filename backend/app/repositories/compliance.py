from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.agent import Agent, AgentRiskLevel
from app.models.agent_tool import AgentTool
from app.models.approval import Approval, ApprovalStatus
from app.models.audit_log import AuditAction, AuditLog
from app.models.execution import Execution, ExecutionStatus
from app.models.incident import Incident, IncidentStatus
from app.models.policy_rule import PolicyRule, PolicyRuleScope


def count_agents(
    db: Session,
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    agent_id: UUID | None = None,
) -> int:
    statement = select(func.count()).select_from(Agent).where(Agent.deleted_at.is_(None))
    if start_at is not None:
        statement = statement.where(Agent.created_at >= start_at)
    if end_at is not None:
        statement = statement.where(Agent.created_at < end_at)
    if agent_id is not None:
        statement = statement.where(Agent.id == agent_id)
    return db.scalar(statement) or 0


def get_agent(db: Session, agent_id: UUID) -> Agent | None:
    statement = select(Agent).where(Agent.id == agent_id, Agent.deleted_at.is_(None))
    return db.scalar(statement)


def count_executions(
    db: Session,
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    agent_id: UUID | None = None,
    status: ExecutionStatus | None = None,
) -> int:
    statement = select(func.count()).select_from(Execution)
    if start_at is not None:
        statement = statement.where(Execution.created_at >= start_at)
    if end_at is not None:
        statement = statement.where(Execution.created_at < end_at)
    if agent_id is not None:
        statement = statement.where(Execution.agent_id == agent_id)
    if status is not None:
        statement = statement.where(Execution.status == status)
    return db.scalar(statement) or 0


def count_approvals(
    db: Session,
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    agent_id: UUID | None = None,
    status: ApprovalStatus | None = None,
) -> int:
    statement = select(func.count()).select_from(Approval)
    if start_at is not None:
        statement = statement.where(Approval.requested_at >= start_at)
    if end_at is not None:
        statement = statement.where(Approval.requested_at < end_at)
    if agent_id is not None:
        statement = statement.where(Approval.agent_id == agent_id)
    if status is not None:
        statement = statement.where(Approval.status == status)
    return db.scalar(statement) or 0


def count_incidents(
    db: Session,
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    agent_id: UUID | None = None,
    status: IncidentStatus | None = None,
    severity: AgentRiskLevel | None = None,
) -> int:
    statement = select(func.count()).select_from(Incident)
    if start_at is not None:
        statement = statement.where(Incident.created_at >= start_at)
    if end_at is not None:
        statement = statement.where(Incident.created_at < end_at)
    if agent_id is not None:
        statement = statement.where(Incident.agent_id == agent_id)
    if status is not None:
        statement = statement.where(Incident.status == status)
    if severity is not None:
        statement = statement.where(Incident.severity == severity)
    return db.scalar(statement) or 0


def count_audit_events(
    db: Session,
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    action: AuditAction | None = None,
) -> int:
    statement = select(func.count()).select_from(AuditLog)
    if start_at is not None:
        statement = statement.where(AuditLog.created_at >= start_at)
    if end_at is not None:
        statement = statement.where(AuditLog.created_at < end_at)
    if action is not None:
        statement = statement.where(AuditLog.action == action)
    return db.scalar(statement) or 0


def count_tools_for_agent(db: Session, agent_id: UUID) -> int:
    statement = (
        select(func.count())
        .select_from(AgentTool)
        .where(AgentTool.agent_id == agent_id, AgentTool.deleted_at.is_(None))
    )
    return db.scalar(statement) or 0


def count_policy_rules_for_agent(db: Session, agent_id: UUID) -> int:
    statement = (
        select(func.count())
        .select_from(PolicyRule)
        .where(
            PolicyRule.deleted_at.is_(None),
            or_(
                PolicyRule.scope == PolicyRuleScope.GLOBAL,
                PolicyRule.agent_id == agent_id,
            ),
        )
    )
    return db.scalar(statement) or 0


def latest_execution_at(db: Session, agent_id: UUID) -> datetime | None:
    return db.scalar(select(func.max(Execution.created_at)).where(Execution.agent_id == agent_id))


def latest_incident_at(db: Session, agent_id: UUID) -> datetime | None:
    return db.scalar(select(func.max(Incident.created_at)).where(Incident.agent_id == agent_id))


def list_incidents(
    db: Session,
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    severity: AgentRiskLevel | None = None,
    status: IncidentStatus | None = None,
    agent_id: UUID | None = None,
) -> tuple[list[Incident], int]:
    filters = []
    if start_at is not None:
        filters.append(Incident.created_at >= start_at)
    if end_at is not None:
        filters.append(Incident.created_at < end_at)
    if severity is not None:
        filters.append(Incident.severity == severity)
    if status is not None:
        filters.append(Incident.status == status)
    if agent_id is not None:
        filters.append(Incident.agent_id == agent_id)

    statement = select(Incident).where(*filters).order_by(Incident.created_at.desc())
    count_statement = select(func.count()).select_from(Incident).where(*filters)
    incidents = list(db.scalars(statement).all())
    total = db.scalar(count_statement) or 0
    return incidents, total
