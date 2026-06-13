from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.agent import AgentRiskLevel
from app.models.risk_compliance import ComplianceStatus, PolicyCoverageStatus
from app.schemas.tool_governance import ToolGovernanceStatus


class RiskRegisterRead(BaseModel):
    id: UUID
    tool_id: UUID
    tool_name: str
    agent_id: UUID
    agent_name: str
    mcp_server_id: UUID
    mcp_server_name: str
    risk_level: AgentRiskLevel
    governance_status: ToolGovernanceStatus
    policy_coverage_status: PolicyCoverageStatus
    compliance_status: ComplianceStatus
    owner_user_id: UUID | None
    last_reviewed_at: datetime | None
    violated_controls: list[str]
    created_at: datetime
    updated_at: datetime


class RiskRegisterListResponse(BaseModel):
    items: list[RiskRegisterRead]
    total: int


class ComplianceControlRead(BaseModel):
    id: UUID
    name: str
    description: str
    severity: AgentRiskLevel
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ControlEvaluation(BaseModel):
    control_name: str
    description: str
    severity: AgentRiskLevel
    passed_tools: int
    failed_tools: int
    affected_tool_ids: list[UUID]
    affected_agent_ids: list[UUID]


class ComplianceEvaluation(BaseModel):
    status: ComplianceStatus
    compliance_score: int
    compliant_tools: int
    warning_tools: int
    non_compliant_tools: int
    violated_controls: list[ControlEvaluation]


class RiskFactor(BaseModel):
    name: str
    count: int
    deduction: int


class AIRiskScore(BaseModel):
    score: int
    factors: list[RiskFactor]
    explanation: str


class RiskSnapshotRead(BaseModel):
    date: date
    risk_score: int
    governed_tools: int
    ungoverned_tools: int
    compliant_tools: int
    non_compliant_tools: int
    open_alerts: int

    model_config = ConfigDict(from_attributes=True)


class RiskSummary(BaseModel):
    risk_score: int
    compliance_score: int
    governed_tools: int
    ungoverned_tools: int
    compliant_tools: int
    non_compliant_tools: int
    high_risk_tools: int
    critical_alerts: int
    compliance_violations: int
    open_governance_risks: int
    risk_trend: list[RiskSnapshotRead]
