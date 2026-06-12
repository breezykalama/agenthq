from datetime import UTC, datetime, time, timedelta

from sqlalchemy.orm import Session

from app.models.agent import AgentRiskLevel
from app.models.approval import ApprovalStatus
from app.models.execution import ExecutionStatus
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
    agents = dashboard_repository.get_agent_metrics(db)
    executions = dashboard_repository.get_execution_metrics(
        db,
        today_start=today_start,
        tomorrow_start=tomorrow_start,
    )
    approvals = dashboard_repository.get_approval_metrics(db)
    incidents = dashboard_repository.get_incident_metrics(db)
    mcp_servers = dashboard_repository.get_mcp_server_metrics(
        db,
        month_start=today_start.replace(day=1),
    )
    users = dashboard_repository.get_user_metrics(db)

    return DashboardSummary(
        total_agents=agents.total,
        active_agents=agents.active,
        disabled_agents=agents.disabled,
        archived_agents=agents.archived,
        total_executions=executions.total,
        executions_today=executions.today,
        succeeded_executions=executions.succeeded,
        failed_executions=executions.failed,
        blocked_executions=executions.blocked,
        requires_approval_executions=executions.requires_approval,
        pending_approvals=approvals.pending,
        approved_approvals=approvals.approved,
        rejected_approvals=approvals.rejected,
        open_incidents=incidents.open,
        investigating_incidents=incidents.investigating,
        resolved_incidents=incidents.resolved,
        critical_incidents=incidents.critical,
        total_mcp_servers=mcp_servers.total,
        connected_mcp_servers=mcp_servers.connected,
        disconnected_mcp_servers=mcp_servers.disconnected,
        discovered_tools=mcp_servers.discovered_tools,
        governed_tools=mcp_servers.governed_tools,
        unreviewed_tools=mcp_servers.unreviewed_tools,
        schema_changes_this_month=mcp_servers.schema_changes_this_month,
        total_users=users.total,
        active_users=users.active,
        total_cost_usd=executions.total_cost_usd,
        average_latency_ms=executions.average_latency_ms,
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
