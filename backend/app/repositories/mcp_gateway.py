from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.tenancy import get_current_organization_id
from app.models.mcp_gateway import MCPGatewayCallRecord, MCPGatewayCallState, MCPGatewayToken


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


def reserve_call_record_pending(
    db: Session,
    *,
    gateway_token_id: UUID,
    tool_id: UUID,
    idempotency_key: str,
    request_hash: str,
) -> bool:
    """Reserve an idempotency key before dispatch. Returns False if the key is already taken.

    INSERT ... ON CONFLICT DO NOTHING on the existing unique index never raises for a duplicate:
    under PostgreSQL a concurrent insert of the same key waits for the other transaction and
    then either inserts (the other rolled back) or does nothing (the other committed). The
    caller commits.
    """
    values = {
        "id": uuid4(),
        "organization_id": get_current_organization_id(db),
        "gateway_token_id": gateway_token_id,
        "tool_id": tool_id,
        "idempotency_key": idempotency_key,
        "state": MCPGatewayCallState.IN_PROGRESS.value,
        "request_hash": request_hash,
        "created_at": datetime.now(UTC),
    }
    conflict_columns = [
        MCPGatewayCallRecord.gateway_token_id,
        MCPGatewayCallRecord.tool_id,
        MCPGatewayCallRecord.idempotency_key,
    ]
    insert = postgresql_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    statement = (
        insert(MCPGatewayCallRecord)
        .values(**values)
        .on_conflict_do_nothing(index_elements=conflict_columns)
        .returning(MCPGatewayCallRecord.id)
    )
    # RETURNING, not rowcount: drivers report -1 as the rowcount of INSERT ... ON CONFLICT.
    return db.execute(statement).scalar_one_or_none() is not None


def complete_call_record_pending(
    db: Session,
    *,
    gateway_token_id: UUID,
    tool_id: UUID,
    idempotency_key: str,
    execution_id: UUID,
    response_payload: dict[str, object],
) -> bool:
    """Finalize this request's own in-progress reservation. The caller commits."""
    statement = (
        update(MCPGatewayCallRecord)
        .where(
            MCPGatewayCallRecord.organization_id == get_current_organization_id(db),
            MCPGatewayCallRecord.gateway_token_id == gateway_token_id,
            MCPGatewayCallRecord.tool_id == tool_id,
            MCPGatewayCallRecord.idempotency_key == idempotency_key,
            MCPGatewayCallRecord.state == MCPGatewayCallState.IN_PROGRESS.value,
        )
        .values(
            state=MCPGatewayCallState.COMPLETED.value,
            execution_id=execution_id,
            response_payload=response_payload,
        )
        .execution_options(synchronize_session=False)
    )
    result = cast(CursorResult[Any], db.execute(statement))
    return result.rowcount == 1
