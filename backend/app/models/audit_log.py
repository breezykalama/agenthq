from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Enum, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.agent import utc_now


class AuditAction(StrEnum):
    AGENT_CREATED = "agent.created"
    AGENT_UPDATED = "agent.updated"
    AGENT_DELETED = "agent.deleted"
    APPROVAL_CREATED = "approval.created"
    APPROVAL_APPROVED = "approval.approved"
    APPROVAL_REJECTED = "approval.rejected"
    APPROVAL_CANCELLED = "approval.cancelled"
    EXECUTION_CREATED = "execution.created"
    EXECUTION_UPDATED = "execution.updated"
    AGENT_TOOL_CREATED = "agent_tool.created"
    AGENT_TOOL_UPDATED = "agent_tool.updated"
    AGENT_TOOL_DELETED = "agent_tool.deleted"
    POLICY_RULE_CREATED = "policy_rule.created"
    POLICY_RULE_UPDATED = "policy_rule.updated"
    POLICY_RULE_DELETED = "policy_rule.deleted"
    POLICY_DECISION_EVALUATED = "policy_decision.evaluated"
    INCIDENT_CREATED = "incident.created"
    INCIDENT_UPDATED = "incident.updated"
    INCIDENT_RESOLVED = "incident.resolved"
    INCIDENT_DISMISSED = "incident.dismissed"
    MCP_SERVER_CREATED = "mcp_server.created"
    MCP_SERVER_UPDATED = "mcp_server.updated"
    MCP_SERVER_DELETED = "mcp_server.deleted"
    MCP_SERVER_SYNCED = "mcp_server.synced"
    MCP_SERVER_SYNC_FAILED = "mcp_server.sync_failed"


JsonObject = dict[str, object]


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    actor: Mapped[str] = mapped_column(String(255), nullable=False, default="system")
    action: Mapped[AuditAction] = mapped_column(
        Enum(
            AuditAction,
            name="audit_action",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    before: Mapped[JsonObject | None] = mapped_column(JSON, nullable=True)
    after: Mapped[JsonObject | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
