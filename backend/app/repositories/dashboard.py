from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agent import Agent, AgentRiskLevel, AgentStatus
from app.models.approval import Approval, ApprovalStatus
from app.models.execution import Execution, ExecutionStatus
from app.models.incident import Incident, IncidentStatus
from app.models.mcp_server import MCPServer, MCPServerStatus
from app.models.user import User


@dataclass(frozen=True)
class AgentMetrics:
    total: int
    active: int
    disabled: int
    archived: int


@dataclass(frozen=True)
class ExecutionMetrics:
    total: int
    today: int
    succeeded: int
    failed: int
    blocked: int
    requires_approval: int
    total_cost_usd: Decimal
    average_latency_ms: float


@dataclass(frozen=True)
class ApprovalMetrics:
    pending: int
    approved: int
    rejected: int


@dataclass(frozen=True)
class IncidentMetrics:
    open: int
    investigating: int
    resolved: int
    critical: int


@dataclass(frozen=True)
class MCPServerMetrics:
    total: int
    connected: int
    disconnected: int


@dataclass(frozen=True)
class UserMetrics:
    total: int
    active: int


def get_agent_metrics(db: Session) -> AgentMetrics:
    row = db.execute(
        select(
            func.count(),
            func.count().filter(Agent.status == AgentStatus.ACTIVE),
            func.count().filter(Agent.status == AgentStatus.DISABLED),
            func.count().filter(Agent.status == AgentStatus.ARCHIVED),
        ).where(Agent.deleted_at.is_(None))
    ).one()
    return AgentMetrics(*row)


def get_execution_metrics(
    db: Session,
    *,
    today_start: datetime,
    tomorrow_start: datetime,
) -> ExecutionMetrics:
    row = db.execute(
        select(
            func.count(),
            func.count().filter(
                Execution.created_at >= today_start,
                Execution.created_at < tomorrow_start,
            ),
            func.count().filter(Execution.status == ExecutionStatus.SUCCEEDED),
            func.count().filter(Execution.status == ExecutionStatus.FAILED),
            func.count().filter(Execution.status == ExecutionStatus.BLOCKED),
            func.count().filter(Execution.status == ExecutionStatus.REQUIRES_APPROVAL),
            func.sum(Execution.cost_usd),
            func.avg(Execution.latency_ms),
        )
    ).one()
    return ExecutionMetrics(
        total=row[0],
        today=row[1],
        succeeded=row[2],
        failed=row[3],
        blocked=row[4],
        requires_approval=row[5],
        total_cost_usd=Decimal("0") if row[6] is None else Decimal(str(row[6])),
        average_latency_ms=0.0 if row[7] is None else float(row[7]),
    )


def get_approval_metrics(db: Session) -> ApprovalMetrics:
    row = db.execute(
        select(
            func.count().filter(Approval.status == ApprovalStatus.PENDING),
            func.count().filter(Approval.status == ApprovalStatus.APPROVED),
            func.count().filter(Approval.status == ApprovalStatus.REJECTED),
        )
    ).one()
    return ApprovalMetrics(*row)


def get_incident_metrics(db: Session) -> IncidentMetrics:
    row = db.execute(
        select(
            func.count().filter(Incident.status == IncidentStatus.OPEN),
            func.count().filter(Incident.status == IncidentStatus.INVESTIGATING),
            func.count().filter(Incident.status == IncidentStatus.RESOLVED),
            func.count().filter(Incident.severity == AgentRiskLevel.CRITICAL),
        )
    ).one()
    return IncidentMetrics(*row)


def get_mcp_server_metrics(db: Session) -> MCPServerMetrics:
    row = db.execute(
        select(
            func.count(),
            func.count().filter(MCPServer.status == MCPServerStatus.CONNECTED),
            func.count().filter(MCPServer.status == MCPServerStatus.DISCONNECTED),
        ).where(MCPServer.deleted_at.is_(None))
    ).one()
    return MCPServerMetrics(*row)


def get_user_metrics(db: Session) -> UserMetrics:
    row = db.execute(
        select(
            func.count(),
            func.count().filter(User.is_active.is_(True)),
        )
    ).one()
    return UserMetrics(*row)


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
