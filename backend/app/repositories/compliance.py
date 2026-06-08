from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.sql import Select

from app.models.agent import Agent, AgentRiskLevel
from app.models.agent_tool import AgentTool
from app.models.approval import Approval, ApprovalStatus
from app.models.audit_log import AuditAction, AuditLog
from app.models.execution import Execution, ExecutionStatus
from app.models.incident import Incident, IncidentStatus
from app.models.policy_rule import PolicyRule, PolicyRuleScope


@dataclass(frozen=True)
class ComplianceSummaryMetrics:
    total_agents: int
    total_executions: int
    blocked_executions: int
    executions_requiring_approval: int
    approved_approvals: int
    rejected_approvals: int
    open_incidents: int
    critical_incidents: int
    policy_decisions_evaluated: int
    audit_events: int


@dataclass(frozen=True)
class AgentReportMetrics:
    tools_count: int
    policy_rules_count: int
    executions_count: int
    blocked_executions: int
    failed_executions: int
    approvals_count: int
    incidents_count: int
    latest_execution_at: datetime | None
    latest_incident_at: datetime | None


def apply_date_filters(
    statement: Select[Any],
    created_at: InstrumentedAttribute[datetime],
    *,
    start_at: datetime | None,
    end_at: datetime | None,
) -> Select[Any]:
    if start_at is not None:
        statement = statement.where(created_at >= start_at)
    if end_at is not None:
        statement = statement.where(created_at < end_at)
    return statement


def get_summary_metrics(
    db: Session,
    *,
    start_at: datetime | None,
    end_at: datetime | None,
    agent_id: UUID | None,
) -> ComplianceSummaryMetrics:
    agent_statement = select(func.count()).select_from(Agent).where(Agent.deleted_at.is_(None))
    execution_statement = select(
        func.count(),
        func.count().filter(Execution.status == ExecutionStatus.BLOCKED),
        func.count().filter(Execution.status == ExecutionStatus.REQUIRES_APPROVAL),
    )
    approval_statement = select(
        func.count().filter(Approval.status == ApprovalStatus.APPROVED),
        func.count().filter(Approval.status == ApprovalStatus.REJECTED),
    )
    incident_statement = select(
        func.count().filter(Incident.status == IncidentStatus.OPEN),
        func.count().filter(Incident.severity == AgentRiskLevel.CRITICAL),
    )
    audit_statement = select(
        func.count().filter(AuditLog.action == AuditAction.POLICY_DECISION_EVALUATED),
        func.count(),
    )

    agent_statement = apply_date_filters(
        agent_statement,
        Agent.created_at,
        start_at=start_at,
        end_at=end_at,
    )
    execution_statement = apply_date_filters(
        execution_statement,
        Execution.created_at,
        start_at=start_at,
        end_at=end_at,
    )
    approval_statement = apply_date_filters(
        approval_statement,
        Approval.requested_at,
        start_at=start_at,
        end_at=end_at,
    )
    incident_statement = apply_date_filters(
        incident_statement,
        Incident.created_at,
        start_at=start_at,
        end_at=end_at,
    )
    audit_statement = apply_date_filters(
        audit_statement,
        AuditLog.created_at,
        start_at=start_at,
        end_at=end_at,
    )
    if agent_id is not None:
        agent_statement = agent_statement.where(Agent.id == agent_id)
        execution_statement = execution_statement.where(Execution.agent_id == agent_id)
        approval_statement = approval_statement.where(Approval.agent_id == agent_id)
        incident_statement = incident_statement.where(Incident.agent_id == agent_id)

    total_agents = db.scalar(agent_statement) or 0
    executions = db.execute(execution_statement).one()
    approvals = db.execute(approval_statement).one()
    incidents = db.execute(incident_statement).one()
    audit_events = db.execute(audit_statement).one()
    return ComplianceSummaryMetrics(
        total_agents=total_agents,
        total_executions=executions[0],
        blocked_executions=executions[1],
        executions_requiring_approval=executions[2],
        approved_approvals=approvals[0],
        rejected_approvals=approvals[1],
        open_incidents=incidents[0],
        critical_incidents=incidents[1],
        policy_decisions_evaluated=audit_events[0],
        audit_events=audit_events[1],
    )


def get_agent(db: Session, agent_id: UUID) -> Agent | None:
    statement = select(Agent).where(Agent.id == agent_id, Agent.deleted_at.is_(None))
    return db.scalar(statement)


def get_agent_report_metrics(db: Session, agent_id: UUID) -> AgentReportMetrics:
    tools_count = (
        select(func.count())
        .select_from(AgentTool)
        .where(AgentTool.agent_id == agent_id, AgentTool.deleted_at.is_(None))
        .scalar_subquery()
    )
    policy_rules_count = (
        select(func.count())
        .select_from(PolicyRule)
        .where(
            PolicyRule.deleted_at.is_(None),
            or_(PolicyRule.scope == PolicyRuleScope.GLOBAL, PolicyRule.agent_id == agent_id),
        )
        .scalar_subquery()
    )
    executions_count = (
        select(func.count()).select_from(Execution).where(Execution.agent_id == agent_id)
    ).scalar_subquery()
    blocked_executions = (
        select(func.count())
        .select_from(Execution)
        .where(Execution.agent_id == agent_id, Execution.status == ExecutionStatus.BLOCKED)
    ).scalar_subquery()
    failed_executions = (
        select(func.count())
        .select_from(Execution)
        .where(Execution.agent_id == agent_id, Execution.status == ExecutionStatus.FAILED)
    ).scalar_subquery()
    approvals_count = (
        select(func.count()).select_from(Approval).where(Approval.agent_id == agent_id)
    ).scalar_subquery()
    incidents_count = (
        select(func.count()).select_from(Incident).where(Incident.agent_id == agent_id)
    ).scalar_subquery()
    latest_execution_at = (
        select(func.max(Execution.created_at)).where(Execution.agent_id == agent_id)
    ).scalar_subquery()
    latest_incident_at = (
        select(func.max(Incident.created_at)).where(Incident.agent_id == agent_id)
    ).scalar_subquery()

    row = db.execute(
        select(
            tools_count,
            policy_rules_count,
            executions_count,
            blocked_executions,
            failed_executions,
            approvals_count,
            incidents_count,
            latest_execution_at,
            latest_incident_at,
        )
    ).one()
    return AgentReportMetrics(*row)


def list_incidents(
    db: Session,
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    severity: AgentRiskLevel | None = None,
    status: IncidentStatus | None = None,
    agent_id: UUID | None = None,
    limit: int,
    offset: int,
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

    statement = (
        select(Incident)
        .where(*filters)
        .order_by(Incident.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    count_statement = select(func.count()).select_from(Incident).where(*filters)
    incidents = list(db.scalars(statement).all())
    total = db.scalar(count_statement) or 0
    return incidents, total
