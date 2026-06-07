from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.agent import utc_now


class MCPServerStatus(StrEnum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class MCPServer(Base):
    __tablename__ = "mcp_servers"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    agent_id: Mapped[UUID | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    server_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[MCPServerStatus] = mapped_column(
        Enum(
            MCPServerStatus,
            name="mcp_server_status",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        default=MCPServerStatus.DISCONNECTED,
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index(
    "ix_mcp_servers_unique_name_not_deleted",
    MCPServer.name,
    unique=True,
    postgresql_where=MCPServer.deleted_at.is_(None),
    sqlite_where=MCPServer.deleted_at.is_(None),
)
