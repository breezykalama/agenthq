from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.agent import AgentRiskLevel
from app.models.agent_tool import AgentToolPermission
from app.models.execution import ExecutionStatus
from app.models.mcp_gateway import MCPGatewayTokenStatus
from app.models.mcp_server import MCPServerStatus
from app.models.policy_rule import PolicyRuleEffect
from app.schemas.tool_governance import ToolGovernanceStatus


class MCPGatewayTokenCreate(BaseModel):
    agent_id: UUID | None = None
    allowed_mcp_server_ids: list[UUID] = Field(default_factory=list)
    mcp_server_id: UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    expires_at: datetime | None = None


class MCPGatewayTokenRead(BaseModel):
    id: UUID
    agent_id: UUID
    allowed_mcp_server_ids: list[UUID]
    mcp_server_id: UUID | None
    name: str
    status: MCPGatewayTokenStatus
    last_used_at: datetime | None
    expires_at: datetime | None
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MCPGatewayTokenCreated(MCPGatewayTokenRead):
    token: str


class MCPGatewayTokenListResponse(BaseModel):
    items: list[MCPGatewayTokenRead]
    total: int


class MCPGatewayInfo(BaseModel):
    mcp_server_id: UUID
    name: str
    status: MCPServerStatus
    linked_agent_id: UUID
    gateway_principal: str


class MCPGatewayTool(BaseModel):
    id: UUID
    name: str
    description: str | None
    input_schema: dict[str, object] | None
    output_schema: dict[str, object] | None
    risk_level: AgentRiskLevel
    permission: AgentToolPermission
    governance_status: ToolGovernanceStatus


class MCPGatewayToolList(BaseModel):
    items: list[MCPGatewayTool]
    total: int


class MCPGatewayToolCall(BaseModel):
    input_payload: dict[str, object] = Field(default_factory=dict)
    approval_id: UUID | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)


class MCPGatewayToolCallResponse(BaseModel):
    execution_id: UUID
    status: ExecutionStatus
    policy_decision: PolicyRuleEffect
    policy_decision_reason: str
    approval_id: UUID | None
    result: dict[str, object] | None = None
    error: str | None = None
    idempotent_replay: bool = False


class MCPGatewayServer(BaseModel):
    id: UUID
    name: str
    status: MCPServerStatus
    linked_agent_id: UUID


class MCPGatewayServerList(BaseModel):
    items: list[MCPGatewayServer]
    total: int
