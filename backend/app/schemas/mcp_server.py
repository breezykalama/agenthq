from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.mcp_server import MCPServerStatus


class MCPServerCreate(BaseModel):
    agent_id: UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    server_url: str = Field(min_length=1, max_length=2048)
    status: MCPServerStatus = MCPServerStatus.DISCONNECTED
    last_sync_at: datetime | None = None


class MCPServerUpdate(BaseModel):
    agent_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    server_url: str | None = Field(default=None, min_length=1, max_length=2048)
    status: MCPServerStatus | None = None
    last_sync_at: datetime | None = None
    last_error: str | None = None


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
