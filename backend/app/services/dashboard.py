from datetime import UTC, datetime, time, timedelta

from sqlalchemy.orm import Session

from app.models.agent import AgentRiskLevel, AgentStatus
from app.models.approval import ApprovalStatus
from app.models.execution import ExecutionStatus
from app.models.incident import IncidentStatus
from app.models.mcp_server import MCPServerStatus
from app.repositories import dashboard as dashboard_repository
from app.schemas.dashboard import (
    AgentsByRisk,
    ApprovalsByStatus,
    DashboardSummary,
    ExecutionsByStatus,
)


def get_summary(db: Session) -> DashboardSummary:
    today_start = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    tomorrow_start = today_start + timedelta(days=1)

    return DashboardSummary(
        total_agents=dashboard_repository.count_agents(db),
        active_agents=dashboard_repository.count_agents(db, AgentStatus.ACTIVE),
        disabled_agents=dashboard_repository.count_agents(db, AgentStatus.DISABLED),
        archived_agents=dashboard_repository.count_agents(db, AgentStatus.ARCHIVED),
        total_executions=dashboard_repository.count_executions(db),
        executions_today=dashboard_repository.count_executions(
            db,
            created_at_start=today_start,
            created_at_end=tomorrow_start,
        ),
        succeeded_executions=dashboard_repository.count_executions(
            db,
            status=ExecutionStatus.SUCCEEDED,
        ),
        failed_executions=dashboard_repository.count_executions(db, status=ExecutionStatus.FAILED),
        blocked_executions=dashboard_repository.count_executions(
            db,
            status=ExecutionStatus.BLOCKED,
        ),
        requires_approval_executions=dashboard_repository.count_executions(
            db,
            status=ExecutionStatus.REQUIRES_APPROVAL,
        ),
        pending_approvals=dashboard_repository.count_approvals(db, ApprovalStatus.PENDING),
        approved_approvals=dashboard_repository.count_approvals(db, ApprovalStatus.APPROVED),
        rejected_approvals=dashboard_repository.count_approvals(db, ApprovalStatus.REJECTED),
        open_incidents=dashboard_repository.count_incidents(db, status=IncidentStatus.OPEN),
        investigating_incidents=dashboard_repository.count_incidents(
            db,
            status=IncidentStatus.INVESTIGATING,
        ),
        resolved_incidents=dashboard_repository.count_incidents(
            db,
            status=IncidentStatus.RESOLVED,
        ),
        critical_incidents=dashboard_repository.count_incidents(
            db,
            severity=AgentRiskLevel.CRITICAL,
        ),
        total_mcp_servers=dashboard_repository.count_mcp_servers(db),
        connected_mcp_servers=dashboard_repository.count_mcp_servers(
            db,
            MCPServerStatus.CONNECTED,
        ),
        disconnected_mcp_servers=dashboard_repository.count_mcp_servers(
            db,
            MCPServerStatus.DISCONNECTED,
        ),
        total_users=dashboard_repository.count_users(db),
        active_users=dashboard_repository.count_users(db, active_only=True),
        total_cost_usd=dashboard_repository.total_execution_cost_usd(db),
        average_latency_ms=dashboard_repository.average_execution_latency_ms(db),
    )


def get_agents_by_risk(db: Session) -> AgentsByRisk:
    counts = dashboard_repository.count_agents_by_risk(db)
    return AgentsByRisk(**{risk.value: counts.get(risk, 0) for risk in AgentRiskLevel})


def get_executions_by_status(db: Session) -> ExecutionsByStatus:
    counts = dashboard_repository.count_executions_by_status(db)
    return ExecutionsByStatus(**{status.value: counts.get(status, 0) for status in ExecutionStatus})


def get_approvals_by_status(db: Session) -> ApprovalsByStatus:
    counts = dashboard_repository.count_approvals_by_status(db)
    return ApprovalsByStatus(**{status.value: counts.get(status, 0) for status in ApprovalStatus})
