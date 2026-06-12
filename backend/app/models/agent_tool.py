from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.agent import AgentRiskLevel, utc_now


class AgentToolPermission(StrEnum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    ADMIN = "admin"


class AgentTool(Base):
    __tablename__ = "agent_tools"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("agents.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovered_from_mcp_server_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("mcp_servers.id"),
        nullable=True,
    )
    input_schema: Mapped[dict[str, object] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )
    output_schema: Mapped[dict[str, object] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )
    schema_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schema_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schema_last_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    permission: Mapped[AgentToolPermission] = mapped_column(
        Enum(
            AgentToolPermission,
            name="agent_tool_permission",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    risk_level: Mapped[AgentRiskLevel] = mapped_column(
        Enum(
            AgentRiskLevel,
            name="agent_risk_level",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index(
    "ix_agent_tools_unique_agent_name_not_deleted",
    AgentTool.agent_id,
    AgentTool.name,
    unique=True,
    postgresql_where=AgentTool.deleted_at.is_(None),
    sqlite_where=AgentTool.deleted_at.is_(None),
)
Index("ix_agent_tools_agent_id_created_at", AgentTool.agent_id, AgentTool.created_at)
Index("ix_agent_tools_organization_id", AgentTool.organization_id)
Index("ix_agent_tools_discovered_from_mcp_server_id", AgentTool.discovered_from_mcp_server_id)
Index("ix_agent_tools_reviewed_at", AgentTool.reviewed_at)
