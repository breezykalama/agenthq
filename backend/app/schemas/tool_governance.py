from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel

from app.models.agent import AgentRiskLevel
from app.models.agent_tool import AgentToolPermission
from app.models.policy_rule import PolicyRuleEffect


class ToolGovernanceStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    REVIEWED = "reviewed"
    GOVERNED = "governed"


class ToolGovernanceRead(BaseModel):
    id: UUID
    agent_id: UUID
    agent_name: str
    mcp_server_id: UUID
    mcp_server_name: str
    name: str
    description: str | None
    governance_status: ToolGovernanceStatus
    risk_level: AgentRiskLevel
    permission: AgentToolPermission
    is_enabled: bool
    policy_count: int
    policy_names: list[str]
    governed_by: list[PolicyRuleEffect]
    input_schema: dict[str, object] | None
    output_schema: dict[str, object] | None
    schema_hash: str | None
    schema_version: int | None
    schema_last_updated_at: datetime | None
    reviewed_by_user_id: UUID | None
    reviewed_at: datetime | None
    active_alerts_count: int
    active_alert_ids: list[UUID]


class ToolGovernanceListResponse(BaseModel):
    items: list[ToolGovernanceRead]
    total: int


class ToolGovernanceSummary(BaseModel):
    total_tools: int
    unreviewed_tools: int
    reviewed_tools: int
    governed_tools: int
    high_risk_tools: int
    schema_changes_this_month: int
    risk_distribution: dict[str, int]
    review_coverage: float
    policy_coverage: float
