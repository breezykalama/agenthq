from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.agent import AgentRiskLevel
from app.models.incident import IncidentStatus
from app.schemas.agent import AgentRead


class ComplianceSummary(BaseModel):
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


class AgentComplianceReport(BaseModel):
    agent: AgentRead
    tools_count: int
    policy_rules_count: int
    executions_count: int
    blocked_executions: int
    failed_executions: int
    approvals_count: int
    incidents_count: int
    latest_execution_at: datetime | None
    latest_incident_at: datetime | None


class ComplianceIncidentRead(BaseModel):
    id: UUID
    agent_id: UUID
    execution_id: UUID | None
    title: str
    severity: AgentRiskLevel
    status: IncidentStatus
    reported_by: str
    assigned_to: str | None
    created_at: datetime
    resolved_at: datetime | None


class ComplianceIncidentListResponse(BaseModel):
    items: list[ComplianceIncidentRead]
    total: int
