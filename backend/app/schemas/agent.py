from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.agent import AgentRiskLevel, AgentStatus


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    owner: str = Field(min_length=1, max_length=255)
    department: str = Field(min_length=1, max_length=255)
    risk_level: AgentRiskLevel
    status: AgentStatus = AgentStatus.DRAFT


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    owner: str | None = Field(default=None, min_length=1, max_length=255)
    department: str | None = Field(default=None, min_length=1, max_length=255)
    risk_level: AgentRiskLevel | None = None
    status: AgentStatus | None = None


class AgentRead(BaseModel):
    id: UUID
    name: str
    description: str | None
    owner: str
    department: str
    risk_level: AgentRiskLevel
    status: AgentStatus
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class AgentListResponse(BaseModel):
    items: list[AgentRead]
    total: int
