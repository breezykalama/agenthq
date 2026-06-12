from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.agent import AgentRiskLevel
from app.models.agent_tool import AgentToolPermission


class AgentToolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    permission: AgentToolPermission
    risk_level: AgentRiskLevel
    is_enabled: bool = True


class AgentToolUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    permission: AgentToolPermission | None = None
    risk_level: AgentRiskLevel | None = None
    is_enabled: bool | None = None


class AgentToolRead(BaseModel):
    id: UUID
    agent_id: UUID
    name: str
    description: str | None
    discovered_from_mcp_server_id: UUID | None
    input_schema: dict[str, object] | None
    output_schema: dict[str, object] | None
    schema_hash: str | None
    schema_version: int | None
    schema_last_updated_at: datetime | None
    reviewed_by_user_id: UUID | None
    reviewed_at: datetime | None
    permission: AgentToolPermission
    risk_level: AgentRiskLevel
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class AgentToolListResponse(BaseModel):
    items: list[AgentToolRead]
    total: int


class AgentToolReview(BaseModel):
    risk_level: AgentRiskLevel
    permission: AgentToolPermission
