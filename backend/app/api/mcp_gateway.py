from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
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
) -> MCPGatewayTokenListResponse:
    items, total = gateway_repository.list_tokens(
        db,
        mcp_server_id=mcp_server_id,
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
