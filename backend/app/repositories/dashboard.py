from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agent import Agent, AgentRiskLevel, AgentStatus
from app.models.approval import Approval, ApprovalStatus
from app.models.execution import Execution, ExecutionStatus
from app.models.incident import Incident, IncidentStatus
from app.models.mcp_server import MCPServer, MCPServerStatus


def count_agents(db: Session, status: AgentStatus | None = None) -> int:
    statement = select(func.count()).select_from(Agent).where(Agent.deleted_at.is_(None))
    if status is not None:
        statement = statement.where(Agent.status == status)
    return db.scalar(statement) or 0


def count_executions(
    db: Session,
    *,
    status: ExecutionStatus | None = None,
    created_at_start: datetime | None = None,
    created_at_end: datetime | None = None,
) -> int:
    statement = select(func.count()).select_from(Execution)
    if status is not None:
        statement = statement.where(Execution.status == status)
    if created_at_start is not None:
        statement = statement.where(Execution.created_at >= created_at_start)
    if created_at_end is not None:
        statement = statement.where(Execution.created_at < created_at_end)
    return db.scalar(statement) or 0


def count_approvals(db: Session, status: ApprovalStatus | None = None) -> int:
    statement = select(func.count()).select_from(Approval)
    if status is not None:
        statement = statement.where(Approval.status == status)
    return db.scalar(statement) or 0


def count_incidents(
    db: Session,
    *,
    status: IncidentStatus | None = None,
    severity: AgentRiskLevel | None = None,
) -> int:
    statement = select(func.count()).select_from(Incident)
    if status is not None:
        statement = statement.where(Incident.status == status)
    if severity is not None:
        statement = statement.where(Incident.severity == severity)
    return db.scalar(statement) or 0


def count_mcp_servers(db: Session, status: MCPServerStatus | None = None) -> int:
    statement = select(func.count()).select_from(MCPServer).where(MCPServer.deleted_at.is_(None))
    if status is not None:
        statement = statement.where(MCPServer.status == status)
    return db.scalar(statement) or 0


def total_execution_cost_usd(db: Session) -> Decimal:
    total = db.scalar(select(func.sum(Execution.cost_usd)).where(Execution.cost_usd.is_not(None)))
    if total is None:
        return Decimal("0")
    return Decimal(str(total))


def average_execution_latency_ms(db: Session) -> float:
    average = db.scalar(
        select(func.avg(Execution.latency_ms)).where(Execution.latency_ms.is_not(None))
    )
    if average is None:
        return 0.0
    return float(average)


def count_agents_by_risk(db: Session) -> dict[AgentRiskLevel, int]:
    statement = (
        select(Agent.risk_level, func.count())
        .where(Agent.deleted_at.is_(None))
        .group_by(Agent.risk_level)
    )
    return {risk_level: count for risk_level, count in db.execute(statement).all()}


def count_executions_by_status(db: Session) -> dict[ExecutionStatus, int]:
    statement = select(Execution.status, func.count()).group_by(Execution.status)
    return {status: count for status, count in db.execute(statement).all()}


def count_approvals_by_status(db: Session) -> dict[ApprovalStatus, int]:
    statement = select(Approval.status, func.count()).group_by(Approval.status)
    return {status: count for status, count in db.execute(statement).all()}
