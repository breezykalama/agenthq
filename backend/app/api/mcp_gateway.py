from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.adapters.mcp_execution import MCPExecutionAdapter, get_mcp_execution_adapter
from app.api.pagination import PaginationParams
from app.core.audit_context import set_request_audit_context
from app.core.rate_limit import enforce_authenticated_rate_limit, enforce_gateway_rate_limit
from app.core.security import OrgPermission, require_current_organization, require_org_permission
from app.db.session import get_db
from app.models.mcp_gateway import MCPGatewayToken
from app.repositories import mcp_gateway as gateway_repository
from app.schemas.mcp_gateway import (
    MCPGatewayInfo,
    MCPGatewayServerList,
    MCPGatewayTokenCreate,
    MCPGatewayTokenCreated,
    MCPGatewayTokenListResponse,
    MCPGatewayTokenRead,
    MCPGatewayToolCall,
    MCPGatewayToolCallResponse,
    MCPGatewayToolList,
)
from app.services import mcp_gateway as gateway_service

management_router = APIRouter(
    prefix="/api/v1/mcp-gateway-tokens",
    tags=["mcp-gateway-tokens"],
    dependencies=[
        Depends(require_current_organization),
        Depends(require_org_permission(OrgPermission.MANAGE_MCP_SERVERS)),
    ],
)
gateway_router = APIRouter(prefix="/api/v1/mcp-gateway", tags=["mcp-gateway"])
rest_gateway_router = APIRouter(prefix="/api/v1/gateway", tags=["gateway"])
mcp_protocol_router = APIRouter(prefix="/api/v1/mcp", tags=["mcp-gateway"])
agent_credential_router = APIRouter(
    prefix="/api/v1/agent-gateway-credentials",
    tags=["agent-gateway-credentials"],
    dependencies=[
        Depends(require_current_organization),
        Depends(require_org_permission(OrgPermission.MANAGE_MCP_SERVERS)),
    ],
)
DatabaseSession = Annotated[Session, Depends(get_db)]
ExecutionAdapter = Annotated[MCPExecutionAdapter, Depends(get_mcp_execution_adapter)]
bearer = HTTPBearer(auto_error=False)


@management_router.post(
    "",
    response_model=MCPGatewayTokenCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_gateway_token(
    create: MCPGatewayTokenCreate,
    request: Request,
    db: DatabaseSession,
) -> MCPGatewayTokenCreated:
    enforce_authenticated_rate_limit(
        request,
        db,
        "gateway_token",
        resource_type="mcp_gateway_token",
        organization_shared=True,
    )
    try:
        return gateway_service.create_token(db, create)
    except gateway_service.MCPGatewayNotFoundError as exc:
        raise HTTPException(status_code=404, detail="MCP server not found.") from exc


@management_router.get("", response_model=MCPGatewayTokenListResponse)
def list_gateway_tokens(
    db: DatabaseSession,
    pagination: PaginationParams,
    mcp_server_id: UUID | None = None,
    agent_id: UUID | None = None,
) -> MCPGatewayTokenListResponse:
    items, total = gateway_repository.list_tokens(
        db,
        mcp_server_id=mcp_server_id,
        agent_id=agent_id,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    return MCPGatewayTokenListResponse(
        items=[MCPGatewayTokenRead.model_validate(item) for item in items],
        total=total,
    )


@management_router.post("/{token_id}/rotate", response_model=MCPGatewayTokenCreated)
def rotate_gateway_token(
    token_id: UUID,
    request: Request,
    db: DatabaseSession,
) -> MCPGatewayTokenCreated:
    enforce_authenticated_rate_limit(
        request,
        db,
        "gateway_token",
        resource_type="mcp_gateway_token",
        resource_id=token_id,
        key_by_resource=True,
    )
    try:
        return gateway_service.rotate_token(db, token_id)
    except gateway_service.MCPGatewayNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Gateway token not found.") from exc


@management_router.post("/{token_id}/revoke", response_model=MCPGatewayTokenRead)
def revoke_gateway_token(
    token_id: UUID,
    request: Request,
    db: DatabaseSession,
) -> MCPGatewayTokenRead:
    enforce_authenticated_rate_limit(
        request,
        db,
        "gateway_token",
        resource_type="mcp_gateway_token",
        resource_id=token_id,
        key_by_resource=True,
    )
    try:
        return MCPGatewayTokenRead.model_validate(gateway_service.revoke_token(db, token_id))
    except gateway_service.MCPGatewayNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Gateway token not found.") from exc


def require_gateway_token(
    mcp_server_id: UUID,
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: DatabaseSession,
) -> MCPGatewayToken:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid gateway token.")
    set_request_audit_context(db, request)
    try:
        return gateway_service.authenticate_token(db, credentials.credentials, mcp_server_id)
    except gateway_service.MCPGatewayTokenInvalidError as exc:
        raise HTTPException(status_code=401, detail="Invalid gateway token.") from exc


GatewayToken = Annotated[MCPGatewayToken, Depends(require_gateway_token)]


def require_agent_gateway_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: DatabaseSession,
) -> MCPGatewayToken:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid gateway credential.")
    set_request_audit_context(db, request)
    try:
        return gateway_service.authenticate_token(db, credentials.credentials)
    except gateway_service.MCPGatewayTokenInvalidError as exc:
        raise HTTPException(status_code=401, detail="Invalid gateway credential.") from exc


AgentGatewayToken = Annotated[MCPGatewayToken, Depends(require_agent_gateway_token)]


@gateway_router.get("/{mcp_server_id}/info", response_model=MCPGatewayInfo)
def get_gateway_info(
    mcp_server_id: UUID,
    request: Request,
    db: DatabaseSession,
    token: GatewayToken,
) -> MCPGatewayInfo:
    enforce_gateway_rate_limit(
        request,
        db,
        "gateway_tools",
        gateway_token_id=token.id,
        organization_id=token.organization_id,
        resource_id=mcp_server_id,
    )
    try:
        return gateway_service.gateway_info(db, token)
    except gateway_service.MCPGatewayNotFoundError as exc:
        raise HTTPException(status_code=404, detail="MCP gateway not found.") from exc


@gateway_router.get("/{mcp_server_id}/tools", response_model=MCPGatewayToolList)
def list_gateway_tools(
    mcp_server_id: UUID,
    request: Request,
    db: DatabaseSession,
    token: GatewayToken,
) -> MCPGatewayToolList:
    enforce_gateway_rate_limit(
        request,
        db,
        "gateway_tools",
        gateway_token_id=token.id,
        organization_id=token.organization_id,
        resource_id=mcp_server_id,
    )
    try:
        return gateway_service.list_gateway_tools(db, token)
    except gateway_service.MCPGatewayNotFoundError as exc:
        raise HTTPException(status_code=404, detail="MCP gateway not found.") from exc


@gateway_router.post(
    "/{mcp_server_id}/tools/{tool_id}/call",
    response_model=MCPGatewayToolCallResponse,
)
def call_gateway_tool(
    mcp_server_id: UUID,
    tool_id: UUID,
    call: MCPGatewayToolCall,
    request: Request,
    db: DatabaseSession,
    token: GatewayToken,
    adapter: ExecutionAdapter,
) -> MCPGatewayToolCallResponse:
    enforce_gateway_rate_limit(
        request,
        db,
        "gateway_call",
        gateway_token_id=token.id,
        organization_id=token.organization_id,
        resource_id=tool_id,
    )
    try:
        return gateway_service.call_gateway_tool(db, token, tool_id, call, adapter)
    except gateway_service.MCPGatewayToolUnavailableError as exc:
        raise HTTPException(status_code=404, detail="Gateway tool not found.") from exc
    except gateway_service.MCPGatewayNotFoundError as exc:
        raise HTTPException(status_code=404, detail="MCP gateway not found.") from exc
    except gateway_service.MCPGatewayApprovalInvalidError as exc:
        raise HTTPException(
            status_code=422,
            detail="Approval is invalid for this gateway tool call.",
        ) from exc


agent_credential_router.add_api_route(
    "",
    create_gateway_token,
    methods=["POST"],
    response_model=MCPGatewayTokenCreated,
    status_code=status.HTTP_201_CREATED,
)
agent_credential_router.add_api_route(
    "",
    list_gateway_tokens,
    methods=["GET"],
    response_model=MCPGatewayTokenListResponse,
)
agent_credential_router.add_api_route(
    "/{token_id}/rotate",
    rotate_gateway_token,
    methods=["POST"],
    response_model=MCPGatewayTokenCreated,
)
agent_credential_router.add_api_route(
    "/{token_id}/revoke",
    revoke_gateway_token,
    methods=["POST"],
    response_model=MCPGatewayTokenRead,
)


@rest_gateway_router.get("/mcp-servers", response_model=MCPGatewayServerList)
def list_rest_gateway_servers(
    request: Request,
    db: DatabaseSession,
    token: AgentGatewayToken,
) -> MCPGatewayServerList:
    enforce_gateway_rate_limit(
        request,
        db,
        "gateway_tools",
        gateway_token_id=token.id,
        organization_id=token.organization_id,
        resource_id=token.agent_id,
    )
    return gateway_service.list_gateway_servers(db, token)


@rest_gateway_router.get("/mcp-servers/{server_id}/tools", response_model=MCPGatewayToolList)
def list_rest_gateway_tools(
    server_id: UUID,
    request: Request,
    db: DatabaseSession,
    token: AgentGatewayToken,
) -> MCPGatewayToolList:
    enforce_gateway_rate_limit(
        request,
        db,
        "gateway_tools",
        gateway_token_id=token.id,
        organization_id=token.organization_id,
        resource_id=server_id,
    )
    try:
        return gateway_service.list_gateway_tools(db, token, server_id, protocol="rest")
    except gateway_service.MCPGatewayNotFoundError as exc:
        raise HTTPException(status_code=404, detail="MCP gateway not found.") from exc


@rest_gateway_router.post(
    "/mcp-servers/{server_id}/tools/{tool_id}/call",
    response_model=MCPGatewayToolCallResponse,
)
def call_rest_gateway_tool(
    server_id: UUID,
    tool_id: UUID,
    call: MCPGatewayToolCall,
    request: Request,
    db: DatabaseSession,
    token: AgentGatewayToken,
    adapter: ExecutionAdapter,
) -> MCPGatewayToolCallResponse:
    enforce_gateway_rate_limit(
        request,
        db,
        "gateway_call",
        gateway_token_id=token.id,
        organization_id=token.organization_id,
        resource_id=tool_id,
    )
    try:
        return gateway_service.call_gateway_tool(
            db, token, tool_id, call, adapter, server_id=server_id, protocol="rest"
        )
    except gateway_service.MCPGatewayToolUnavailableError as exc:
        raise HTTPException(status_code=404, detail="Gateway tool not found.") from exc
    except gateway_service.MCPGatewayNotFoundError as exc:
        raise HTTPException(status_code=404, detail="MCP gateway not found.") from exc
    except gateway_service.MCPGatewayApprovalInvalidError as exc:
        raise HTTPException(
            status_code=422,
            detail="Approval is invalid for this gateway tool call.",
        ) from exc


def mcp_error(request_id: object, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
    )


@mcp_protocol_router.post("/{server_id}")
def mcp_streamable_http(
    server_id: UUID,
    payload: Annotated[object, Body()],
    request: Request,
    db: DatabaseSession,
    token: AgentGatewayToken,
    adapter: ExecutionAdapter,
) -> Response:
    if not isinstance(payload, dict):
        return mcp_error(None, -32600, "Invalid JSON-RPC request.")
    request_id = payload.get("id")
    method = payload.get("method")
    if method == "notifications/initialized":
        return Response(status_code=202)
    if method == "initialize":
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "AgentHQ Governed Gateway", "version": "0.8.0"},
                },
            }
        )
    try:
        if method == "tools/list":
            enforce_gateway_rate_limit(
                request, db, "gateway_tools", gateway_token_id=token.id,
                organization_id=token.organization_id, resource_id=server_id,
            )
            tools = gateway_service.list_gateway_tools(db, token, server_id, protocol="mcp")
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [
                            {
                                "name": tool.name,
                                "description": tool.description or "",
                                "inputSchema": tool.input_schema or {"type": "object"},
                            }
                            for tool in tools.items
                        ]
                    },
                }
            )
        if method == "tools/call":
            params = payload.get("params")
            if not isinstance(params, dict) or not isinstance(params.get("name"), str):
                return mcp_error(request_id, -32602, "Invalid tool call parameters.")
            arguments = params.get("arguments", {})
            if not isinstance(arguments, dict):
                return mcp_error(request_id, -32602, "Invalid tool call parameters.")
            metadata = params.get("_meta", {})
            metadata = metadata if isinstance(metadata, dict) else {}
            approval = metadata.get("approval_id") or arguments.pop("_agenthq_approval_id", None)
            idempotency = metadata.get("idempotency_key") or arguments.pop(
                "_agenthq_idempotency_key",
                None,
            )
            try:
                call = MCPGatewayToolCall(
                    input_payload=arguments,
                    approval_id=approval,
                    idempotency_key=idempotency,
                )
            except ValidationError:
                return mcp_error(request_id, -32602, "Invalid tool call parameters.")
            enforce_gateway_rate_limit(
                request, db, "gateway_call", gateway_token_id=token.id,
                organization_id=token.organization_id, resource_id=server_id,
            )
            result = gateway_service.call_gateway_tool_by_name(
                db, token, server_id, params["name"], call, adapter, protocol="mcp"
            )
            if result.status.value in {"blocked", "requires_approval", "failed"}:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": result.error or result.policy_decision_reason,
                                }
                            ],
                            "isError": True,
                        },
                    }
                )
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result.result or {"content": []},
                }
            )
    except gateway_service.MCPGatewayApprovalInvalidError:
        return mcp_error(request_id, -32003, "Approval is invalid for this tool call.")
    except (
        gateway_service.MCPGatewayNotFoundError,
        gateway_service.MCPGatewayToolUnavailableError,
    ):
        return mcp_error(request_id, -32004, "Gateway resource not found.")
    return mcp_error(request_id, -32601, "Method not found.")


@mcp_protocol_router.get("/{server_id}")
def mcp_streamable_http_get(server_id: UUID, token: AgentGatewayToken) -> JSONResponse:
    return mcp_error(None, -32000, "This gateway does not expose a server event stream.")


@mcp_protocol_router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def mcp_streamable_http_delete(server_id: UUID, token: AgentGatewayToken) -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)
