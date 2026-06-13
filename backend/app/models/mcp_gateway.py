from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.agent import utc_now


class MCPGatewayTokenStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class MCPGatewayToken(Base):
    __tablename__ = "mcp_gateway_tokens"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    mcp_server_id: Mapped[UUID] = mapped_column(ForeignKey("mcp_servers.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[MCPGatewayTokenStatus] = mapped_column(
        Enum(
            MCPGatewayTokenStatus,
            name="mcp_gateway_token_status",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        default=MCPGatewayTokenStatus.ACTIVE,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class MCPGatewayCallRecord(Base):
    __tablename__ = "mcp_gateway_call_records"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    gateway_token_id: Mapped[UUID] = mapped_column(
        ForeignKey("mcp_gateway_tokens.id"),
        nullable=False,
    )
    tool_id: Mapped[UUID] = mapped_column(ForeignKey("agent_tools.id"), nullable=False)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("executions.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    response_payload: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


Index(
    "ix_mcp_gateway_tokens_organization_server",
    MCPGatewayToken.organization_id,
    MCPGatewayToken.mcp_server_id,
)
Index(
    "ix_mcp_gateway_call_records_idempotency",
    MCPGatewayCallRecord.gateway_token_id,
    MCPGatewayCallRecord.tool_id,
    MCPGatewayCallRecord.idempotency_key,
    unique=True,
)
