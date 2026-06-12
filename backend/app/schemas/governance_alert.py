from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.governance_alert import (
    GovernanceAlertSeverity,
    GovernanceAlertStatus,
    GovernanceAlertType,
)


class GovernanceAlertRead(BaseModel):
    id: UUID
    organization_id: UUID
    alert_type: GovernanceAlertType
    severity: GovernanceAlertSeverity
    status: GovernanceAlertStatus
    agent_id: UUID | None
    tool_id: UUID | None
    mcp_server_id: UUID | None
    title: str
    description: str
    metadata: dict[str, object] | None = Field(validation_alias="alert_metadata")
    acknowledged_by_user_id: UUID | None
    acknowledged_at: datetime | None
    resolved_by_user_id: UUID | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class GovernanceAlertListResponse(BaseModel):
    items: list[GovernanceAlertRead]
    total: int


class GovernanceHealthMetrics(BaseModel):
    unreviewed_tools: int
    high_risk_unreviewed_tools: int
    ungoverned_tools: int
    unresolved_critical_alerts: int
    unresolved_high_alerts: int


class GovernanceHealthScore(BaseModel):
    score: int
    metrics: GovernanceHealthMetrics
    open_alerts: int
    critical_alerts: int
    governance_gaps: int
    explanation: str
