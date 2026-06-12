from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from app.core.tenancy import get_current_organization_id
from app.models.agent import Agent, AgentRiskLevel, AgentStatus
from app.models.agent_tool import AgentTool
from app.models.approval import Approval, ApprovalStatus
from app.models.audit_log import AuditAction, AuditLog
from app.models.execution import Execution, ExecutionStatus
from app.models.governance_alert import (
    GovernanceAlert,
    GovernanceAlertSeverity,
    GovernanceAlertStatus,
)
from app.models.incident import Incident, IncidentStatus
from app.models.mcp_server import MCPServer, MCPServerStatus
from app.models.organization import OrganizationMembership
from app.models.policy_rule import PolicyRule, PolicyRuleScope
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
    discovered_tools: int
    governed_tools: int
    unreviewed_tools: int
    schema_changes_this_month: int
    high_risk_unreviewed_tools: int
    open_alerts: int
    critical_alerts: int
    high_alerts: int


@dataclass(frozen=True)
class UserMetrics:
    total: int
    active: int


def get_agent_metrics(db: Session) -> AgentMetrics:
    organization_id = get_current_organization_id(db)
    row = db.execute(
        select(
            func.count(),
            func.count().filter(Agent.status == AgentStatus.ACTIVE),
            func.count().filter(Agent.status == AgentStatus.DISABLED),
            func.count().filter(Agent.status == AgentStatus.ARCHIVED),
        ).where(Agent.organization_id == organization_id, Agent.deleted_at.is_(None))
    ).one()
    return AgentMetrics(*row)


def get_execution_metrics(
    db: Session,
    *,
    today_start: datetime,
    tomorrow_start: datetime,
) -> ExecutionMetrics:
    organization_id = get_current_organization_id(db)
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
        ).where(Execution.organization_id == organization_id)
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
    organization_id = get_current_organization_id(db)
    row = db.execute(
        select(
            func.count().filter(Approval.status == ApprovalStatus.PENDING),
            func.count().filter(Approval.status == ApprovalStatus.APPROVED),
            func.count().filter(Approval.status == ApprovalStatus.REJECTED),
        ).where(Approval.organization_id == organization_id)
    ).one()
    return ApprovalMetrics(*row)


def get_incident_metrics(db: Session) -> IncidentMetrics:
    organization_id = get_current_organization_id(db)
    row = db.execute(
        select(
            func.count().filter(Incident.status == IncidentStatus.OPEN),
            func.count().filter(Incident.status == IncidentStatus.INVESTIGATING),
            func.count().filter(Incident.status == IncidentStatus.RESOLVED),
            func.count().filter(Incident.severity == AgentRiskLevel.CRITICAL),
        ).where(Incident.organization_id == organization_id)
    ).one()
    return IncidentMetrics(*row)


def get_mcp_server_metrics(db: Session, *, month_start: datetime) -> MCPServerMetrics:
    organization_id = get_current_organization_id(db)
    policy_exists = exists(
        select(PolicyRule.id).where(
            PolicyRule.organization_id == organization_id,
            PolicyRule.deleted_at.is_(None),
            PolicyRule.is_enabled.is_(True),
            or_(
                PolicyRule.scope == PolicyRuleScope.GLOBAL,
                and_(
                    PolicyRule.scope == PolicyRuleScope.AGENT,
                    PolicyRule.agent_id == AgentTool.agent_id,
                ),
                and_(
                    PolicyRule.scope == PolicyRuleScope.TOOL,
                    PolicyRule.tool_id == AgentTool.id,
                ),
            ),
        )
    )
    discovered_filter = (
        AgentTool.organization_id == organization_id,
        AgentTool.deleted_at.is_(None),
        AgentTool.discovered_from_mcp_server_id.is_not(None),
    )
    discovered_tools = (
        select(func.count()).select_from(AgentTool).where(*discovered_filter).scalar_subquery()
    )
    governed_tools = (
        select(func.count())
        .select_from(AgentTool)
        .where(*discovered_filter, AgentTool.reviewed_at.is_not(None), policy_exists)
        .scalar_subquery()
    )
    unreviewed_tools = (
        select(func.count())
        .select_from(AgentTool)
        .where(*discovered_filter, AgentTool.reviewed_at.is_(None))
        .scalar_subquery()
    )
    schema_changes = (
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.organization_id == organization_id,
            AuditLog.action == AuditAction.MCP_TOOL_SCHEMA_CHANGED,
            AuditLog.created_at >= month_start,
        )
        .scalar_subquery()
    )
    high_risk_unreviewed = (
        select(func.count())
        .select_from(AgentTool)
        .where(
            *discovered_filter,
            AgentTool.reviewed_at.is_(None),
            AgentTool.risk_level.in_((AgentRiskLevel.HIGH, AgentRiskLevel.CRITICAL)),
        )
        .scalar_subquery()
    )
    active_alert_statuses = (GovernanceAlertStatus.OPEN, GovernanceAlertStatus.ACKNOWLEDGED)
    open_alerts = (
        select(func.count())
        .select_from(GovernanceAlert)
        .where(
            GovernanceAlert.organization_id == organization_id,
            GovernanceAlert.status.in_(active_alert_statuses),
        )
        .scalar_subquery()
    )
    critical_alerts = (
        select(func.count())
        .select_from(GovernanceAlert)
        .where(
            GovernanceAlert.organization_id == organization_id,
            GovernanceAlert.status.in_(active_alert_statuses),
            GovernanceAlert.severity == GovernanceAlertSeverity.CRITICAL,
        )
        .scalar_subquery()
    )
    high_alerts = (
        select(func.count())
        .select_from(GovernanceAlert)
        .where(
            GovernanceAlert.organization_id == organization_id,
            GovernanceAlert.status.in_(active_alert_statuses),
            GovernanceAlert.severity == GovernanceAlertSeverity.HIGH,
        )
        .scalar_subquery()
    )
    row = db.execute(
        select(
            func.count(),
            func.count().filter(MCPServer.status == MCPServerStatus.CONNECTED),
            func.count().filter(MCPServer.status == MCPServerStatus.DISCONNECTED),
            discovered_tools,
            governed_tools,
            unreviewed_tools,
            schema_changes,
            high_risk_unreviewed,
            open_alerts,
            critical_alerts,
            high_alerts,
        ).where(
            MCPServer.organization_id == organization_id,
            MCPServer.deleted_at.is_(None),
        )
    ).one()
    return MCPServerMetrics(*row)


def get_user_metrics(db: Session) -> UserMetrics:
    organization_id = get_current_organization_id(db)
    row = db.execute(
        select(
            func.count(),
            func.count().filter(User.is_active.is_(True)),
        )
        .select_from(User)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.is_active.is_(True),
        )
    ).one()
    return UserMetrics(*row)


def count_agents_by_risk(db: Session) -> dict[AgentRiskLevel, int]:
    statement = (
        select(Agent.risk_level, func.count())
        .where(
            Agent.organization_id == get_current_organization_id(db),
            Agent.deleted_at.is_(None),
        )
        .group_by(Agent.risk_level)
    )
    return {risk_level: count for risk_level, count in db.execute(statement).all()}


def count_executions_by_status(db: Session) -> dict[ExecutionStatus, int]:
    statement = (
        select(Execution.status, func.count())
        .where(Execution.organization_id == get_current_organization_id(db))
        .group_by(Execution.status)
    )
    return {status: count for status, count in db.execute(statement).all()}


def count_approvals_by_status(db: Session) -> dict[ApprovalStatus, int]:
    statement = (
        select(Approval.status, func.count())
        .where(Approval.organization_id == get_current_organization_id(db))
        .group_by(Approval.status)
    )
    return {status: count for status, count in db.execute(statement).all()}
