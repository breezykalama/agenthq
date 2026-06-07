from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.adapters.mcp_discovery import MCPDiscoveryAdapter, get_mcp_discovery_adapter
from app.core.security import require_roles
from app.db.session import get_db
from app.models.user import UserRole
from app.schemas.mcp_server import (
    MCPServerCreate,
    MCPServerListResponse,
    MCPServerRead,
    MCPServerSyncResponse,
    MCPServerUpdate,
)
from app.services import mcp_servers as mcp_server_service

router = APIRouter(
    prefix="/api/v1/mcp-servers",
    tags=["mcp-servers"],
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
DatabaseSession = Annotated[Session, Depends(get_db)]
DiscoveryAdapter = Annotated[MCPDiscoveryAdapter, Depends(get_mcp_discovery_adapter)]


@router.post("", response_model=MCPServerRead, status_code=status.HTTP_201_CREATED)
def create_mcp_server(
    mcp_server_create: MCPServerCreate,
    db: DatabaseSession,
) -> MCPServerRead:
    try:
        return MCPServerRead.model_validate(
            mcp_server_service.create_mcp_server(db, mcp_server_create)
        )
    except mcp_server_service.DuplicateMCPServerNameError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An MCP server with this name already exists.",
        ) from exc


@router.get("", response_model=MCPServerListResponse)
def list_mcp_servers(db: DatabaseSession) -> MCPServerListResponse:
    mcp_servers, total = mcp_server_service.list_mcp_servers(db)
    return MCPServerListResponse(
        items=[MCPServerRead.model_validate(mcp_server) for mcp_server in mcp_servers],
        total=total,
    )


@router.get("/{mcp_server_id}", response_model=MCPServerRead)
def get_mcp_server(mcp_server_id: UUID, db: DatabaseSession) -> MCPServerRead:
    try:
        return MCPServerRead.model_validate(
            mcp_server_service.get_mcp_server_by_id(db, mcp_server_id)
        )
    except mcp_server_service.MCPServerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="MCP server not found.",
        ) from exc


@router.patch("/{mcp_server_id}", response_model=MCPServerRead)
def update_mcp_server(
    mcp_server_id: UUID,
    mcp_server_update: MCPServerUpdate,
    db: DatabaseSession,
) -> MCPServerRead:
    try:
        return MCPServerRead.model_validate(
            mcp_server_service.update_mcp_server(db, mcp_server_id, mcp_server_update)
        )
    except mcp_server_service.MCPServerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="MCP server not found.",
        ) from exc
    except mcp_server_service.DuplicateMCPServerNameError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An MCP server with this name already exists.",
        ) from exc


@router.delete("/{mcp_server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mcp_server(mcp_server_id: UUID, db: DatabaseSession) -> None:
    try:
        mcp_server_service.soft_delete_mcp_server(db, mcp_server_id)
    except mcp_server_service.MCPServerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="MCP server not found.",
        ) from exc


@router.post("/{mcp_server_id}/sync", response_model=MCPServerSyncResponse)
def sync_mcp_server(
    mcp_server_id: UUID,
    db: DatabaseSession,
    adapter: DiscoveryAdapter,
) -> MCPServerSyncResponse:
    try:
        return mcp_server_service.sync_mcp_server(db, mcp_server_id, adapter)
    except mcp_server_service.MCPServerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="MCP server not found.",
        ) from exc
    except mcp_server_service.MCPServerSyncError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
