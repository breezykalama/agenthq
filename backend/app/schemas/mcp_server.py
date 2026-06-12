import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.mcp_urls import validate_mcp_server_url
from app.models.mcp_server import MCPAuthType, MCPServerStatus, MCPTransportType

SECRET_REF_PATTERN = re.compile(r"^MCP_AUTH_[A-Z0-9_]{1,246}$")


def validate_auth_configuration(auth_type: MCPAuthType, auth_secret_ref: str | None) -> None:
    if auth_type == MCPAuthType.NONE:
        if auth_secret_ref is not None:
            raise ValueError("auth_secret_ref is only allowed when MCP authentication is enabled.")
        return
    if auth_secret_ref is None or not SECRET_REF_PATTERN.fullmatch(auth_secret_ref):
        raise ValueError(
            "Authenticated MCP servers require an MCP_AUTH_* environment-variable reference."
        )


class MCPServerCreate(BaseModel):
    agent_id: UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    server_url: str = Field(min_length=1, max_length=2048)
    transport_type: MCPTransportType = MCPTransportType.STREAMABLE_HTTP
    auth_type: MCPAuthType = MCPAuthType.NONE
    auth_secret_ref: str | None = Field(default=None, max_length=255)
    request_timeout_seconds: int = Field(default=30, ge=1, le=120)
    connect_timeout_seconds: int = Field(default=10, ge=1, le=30)
    status: MCPServerStatus = MCPServerStatus.DISCONNECTED
    last_sync_at: datetime | None = None

    @field_validator("server_url")
    @classmethod
    def validate_server_url(cls, value: str) -> str:
        return validate_mcp_server_url(value)

    @model_validator(mode="after")
    def validate_auth(self) -> "MCPServerCreate":
        validate_auth_configuration(self.auth_type, self.auth_secret_ref)
        return self


class MCPServerUpdate(BaseModel):
    agent_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    server_url: str | None = Field(default=None, min_length=1, max_length=2048)
    transport_type: MCPTransportType | None = None
    auth_type: MCPAuthType | None = None
    auth_secret_ref: str | None = Field(default=None, max_length=255)
    request_timeout_seconds: int | None = Field(default=None, ge=1, le=120)
    connect_timeout_seconds: int | None = Field(default=None, ge=1, le=30)
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
    transport_type: MCPTransportType
    auth_type: MCPAuthType
    auth_secret_ref: str | None
    request_timeout_seconds: int
    connect_timeout_seconds: int
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
