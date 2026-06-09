from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.mcp_urls import validate_mcp_server_url
from app.models.mcp_server import MCPServerStatus


class MCPServerCreate(BaseModel):
    agent_id: UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    server_url: str = Field(min_length=1, max_length=2048)
    status: MCPServerStatus = MCPServerStatus.DISCONNECTED
    last_sync_at: datetime | None = None

    @field_validator("server_url")
    @classmethod
    def validate_server_url(cls, value: str) -> str:
        return validate_mcp_server_url(value)


class MCPServerUpdate(BaseModel):
    agent_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    server_url: str | None = Field(default=None, min_length=1, max_length=2048)
    status: MCPServerStatus | None = None
    last_sync_at: datetime | None = None
    last_error: str | None = Field(default=None, max_length=2000)

    @field_validator("server_url")
    @classmethod
    def validate_server_url(cls, value: str | None) -> str | None:
        return validate_mcp_server_url(value) if value is not None else None


class MCPServerRead(BaseModel):
    id: UUID
    agent_id: UUID | None
    name: str
    description: str | None
    server_url: str
    status: MCPServerStatus
    last_sync_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class MCPServerListResponse(BaseModel):
    items: list[MCPServerRead]
    total: int


class MCPServerSyncResponse(BaseModel):
    server_id: UUID
    agent_id: UUID
    discovered_tools_count: int
    created_tools_count: int
    updated_tools_count: int
    status: MCPServerStatus
    last_sync_at: datetime
