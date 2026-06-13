from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.tenancy import get_current_organization_id
from app.models.mcp_gateway import MCPGatewayCallRecord, MCPGatewayToken


def create_token_pending(db: Session, token: MCPGatewayToken) -> MCPGatewayToken:
    db.add(token)
    db.flush()
    return token


def list_tokens(
    db: Session,
    *,
    mcp_server_id: UUID | None,
    agent_id: UUID | None = None,
    limit: int,
    offset: int,
) -> tuple[list[MCPGatewayToken], int]:
    filters = [MCPGatewayToken.organization_id == get_current_organization_id(db)]
    if mcp_server_id is not None:
        filters.append(MCPGatewayToken.mcp_server_id == mcp_server_id)
    if agent_id is not None:
        filters.append(MCPGatewayToken.agent_id == agent_id)
    statement = (
        select(MCPGatewayToken)
        .where(*filters)
        .order_by(MCPGatewayToken.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    count_statement = select(func.count()).select_from(MCPGatewayToken).where(*filters)
    return list(db.scalars(statement).all()), db.scalar(count_statement) or 0


def get_token_by_id(db: Session, token_id: UUID) -> MCPGatewayToken | None:
    return db.scalar(
        select(MCPGatewayToken).where(
            MCPGatewayToken.organization_id == get_current_organization_id(db),
            MCPGatewayToken.id == token_id,
        )
    )


def get_token_by_hash(db: Session, token_hash: str) -> MCPGatewayToken | None:
    return db.scalar(select(MCPGatewayToken).where(MCPGatewayToken.token_hash == token_hash))


def update_token_pending(
    db: Session,
    token: MCPGatewayToken,
    values: dict[str, object],
) -> MCPGatewayToken:
    for field, value in values.items():
        setattr(token, field, value)
    db.add(token)
    db.flush()
    return token


def mark_token_used_pending(db: Session, token: MCPGatewayToken) -> None:
    token.last_used_at = datetime.now(UTC)
    db.add(token)
    db.flush()


def get_call_record(
    db: Session,
    *,
    gateway_token_id: UUID,
    tool_id: UUID,
    idempotency_key: str,
) -> MCPGatewayCallRecord | None:
    return db.scalar(
        select(MCPGatewayCallRecord).where(
            MCPGatewayCallRecord.organization_id == get_current_organization_id(db),
            MCPGatewayCallRecord.gateway_token_id == gateway_token_id,
            MCPGatewayCallRecord.tool_id == tool_id,
            MCPGatewayCallRecord.idempotency_key == idempotency_key,
        )
    )


def create_call_record_pending(
    db: Session,
    record: MCPGatewayCallRecord,
) -> MCPGatewayCallRecord:
    db.add(record)
    db.flush()
    return record
