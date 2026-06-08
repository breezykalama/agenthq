from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.tenancy import get_current_organization_id
from app.models.mcp_server import MCPServer, MCPServerStatus
from app.schemas.mcp_server import MCPServerCreate


def create_mcp_server(db: Session, mcp_server_create: MCPServerCreate) -> MCPServer:
    mcp_server = MCPServer(
        organization_id=get_current_organization_id(db),
        **mcp_server_create.model_dump(),
    )
    db.add(mcp_server)
    db.commit()
    db.refresh(mcp_server)
    return mcp_server


def list_mcp_servers(db: Session, *, limit: int, offset: int) -> tuple[list[MCPServer], int]:
    filters = [
        MCPServer.organization_id == get_current_organization_id(db),
        MCPServer.deleted_at.is_(None),
    ]
    statement = (
        select(MCPServer)
        .where(*filters)
        .order_by(MCPServer.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    count_statement = select(func.count()).select_from(MCPServer).where(*filters)
    return list(db.scalars(statement).all()), db.scalar(count_statement) or 0


def get_mcp_server_by_id(db: Session, mcp_server_id: UUID) -> MCPServer | None:
    statement = select(MCPServer).where(
        MCPServer.organization_id == get_current_organization_id(db),
        MCPServer.id == mcp_server_id,
        MCPServer.deleted_at.is_(None),
    )
    return db.scalar(statement)


def get_mcp_server_by_name(db: Session, name: str) -> MCPServer | None:
    statement = select(MCPServer).where(
        MCPServer.organization_id == get_current_organization_id(db),
        MCPServer.name == name,
        MCPServer.deleted_at.is_(None),
    )
    return db.scalar(statement)


def update_mcp_server(
    db: Session,
    mcp_server: MCPServer,
    values: dict[str, object],
) -> MCPServer:
    for field, value in values.items():
        setattr(mcp_server, field, value)
    db.add(mcp_server)
    db.commit()
    db.refresh(mcp_server)
    return mcp_server


def update_mcp_server_state(
    db: Session,
    mcp_server: MCPServer,
    values: dict[str, object],
) -> MCPServer:
    return update_mcp_server(db, mcp_server, values)


def update_mcp_server_state_pending(
    db: Session,
    mcp_server: MCPServer,
    values: dict[str, object],
) -> MCPServer:
    for field, value in values.items():
        setattr(mcp_server, field, value)
    db.add(mcp_server)
    db.flush()
    return mcp_server


def soft_delete_mcp_server(db: Session, mcp_server: MCPServer) -> MCPServer:
    mcp_server.deleted_at = datetime.now(UTC)
    db.add(mcp_server)
    db.commit()
    db.refresh(mcp_server)
    return mcp_server


def count_mcp_servers(db: Session, status: MCPServerStatus | None = None) -> int:
    statement = (
        select(func.count())
        .select_from(MCPServer)
        .where(
            MCPServer.organization_id == get_current_organization_id(db),
            MCPServer.deleted_at.is_(None),
        )
    )
    if status is not None:
        statement = statement.where(MCPServer.status == status)
    return db.scalar(statement) or 0
