from decimal import Decimal

from pydantic import BaseModel


class DashboardSummary(BaseModel):
    total_agents: int
    active_agents: int
    disabled_agents: int
    archived_agents: int
    total_executions: int
    executions_today: int
    succeeded_executions: int
    failed_executions: int
    blocked_executions: int
    requires_approval_executions: int
    pending_approvals: int
    approved_approvals: int
    rejected_approvals: int
    open_incidents: int
    investigating_incidents: int
    resolved_incidents: int
    critical_incidents: int
    total_mcp_servers: int
    connected_mcp_servers: int
    disconnected_mcp_servers: int
    discovered_tools: int
    governed_tools: int
    unreviewed_tools: int
    schema_changes_this_month: int
    governance_health: int
    open_governance_alerts: int
    critical_governance_alerts: int
    governance_gaps: int
    policy_coverage_percentage: float
    total_users: int
    active_users: int
    total_cost_usd: Decimal
    average_latency_ms: float


class AgentsByRisk(BaseModel):
    low: int
    medium: int
    high: int
    critical: int


class ExecutionsByStatus(BaseModel):
    pending: int
    running: int
    succeeded: int
    failed: int
    blocked: int
    requires_approval: int


class ApprovalsByStatus(BaseModel):
    pending: int
    approved: int
    rejected: int
    cancelled: int
