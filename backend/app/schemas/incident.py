from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.agent import AgentRiskLevel
from app.models.incident import IncidentStatus


class IncidentCreate(BaseModel):
    agent_id: UUID
    execution_id: UUID | None = None
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=5000)
    severity: AgentRiskLevel
    status: IncidentStatus = IncidentStatus.OPEN
    reported_by: str = Field(default="system", min_length=1, max_length=255)
    assigned_to: str | None = Field(default=None, max_length=255)
    resolution_notes: str | None = Field(default=None, max_length=2000)


class IncidentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1, max_length=5000)
    severity: AgentRiskLevel | None = None
    status: IncidentStatus | None = None
    assigned_to: str | None = Field(default=None, max_length=255)
    resolution_notes: str | None = Field(default=None, max_length=2000)


class IncidentDecision(BaseModel):
    resolution_notes: str | None = Field(default=None, max_length=2000)


class IncidentRead(BaseModel):
    id: UUID
    agent_id: UUID
    execution_id: UUID | None
    title: str
    description: str
    severity: AgentRiskLevel
    status: IncidentStatus
    reported_by: str
    assigned_to: str | None
    resolution_notes: str | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class IncidentListResponse(BaseModel):
    items: list[IncidentRead]
    total: int
