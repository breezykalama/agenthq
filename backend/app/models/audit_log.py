from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, String, Uuid, event
from sqlalchemy.orm import Mapped, Mapper, mapped_column

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
    EXECUTION_STARTED = "execution.started"
    EXECUTION_COMPLETED = "execution.completed"
    EXECUTION_FAILED = "execution.failed"
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
    MCP_TOOL_DISCOVERED = "mcp_tool.discovered"
    MCP_TOOL_REMOVED = "mcp_tool.removed"
    MCP_TOOL_SCHEMA_CHANGED = "mcp_tool.schema_changed"
    MCP_TOOL_DESCRIPTION_CHANGED = "mcp_tool.description_changed"
    MCP_TOOL_REVIEWED = "mcp_tool.reviewed"
    MCP_TOOL_RISK_CHANGED = "mcp_tool.risk_changed"
    MCP_TOOL_PERMISSION_CHANGED = "mcp_tool.permission_changed"
    GOVERNANCE_ALERT_CREATED = "governance_alert.created"
    GOVERNANCE_ALERT_ACKNOWLEDGED = "governance_alert.acknowledged"
    GOVERNANCE_ALERT_RESOLVED = "governance_alert.resolved"
    GOVERNANCE_ALERT_REOPENED = "governance_alert.reopened"
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_LOGIN = "user.login"
    USER_DEACTIVATED = "user.deactivated"
    ORGANIZATION_CREATED = "organization.created"
    ORGANIZATION_MEMBERSHIP_CREATED = "organization_membership.created"
    ORGANIZATION_INVITE_CREATED = "organization_invite.created"
    ORGANIZATION_INVITE_ACCEPTED = "organization_invite.accepted"
    ORGANIZATION_INVITE_REVOKED = "organization_invite.revoked"
    AUTH_LOGIN_FAILED = "auth.login_failed"
    SECURITY_ACCESS_DENIED = "security.access_denied"
    SECURITY_CROSS_ORG_ACCESS_DENIED = "security.cross_org_access_denied"
    SECURITY_INACTIVE_MEMBERSHIP_DENIED = "security.inactive_membership_denied"
    SECURITY_RATE_LIMITED = "security.rate_limited"
    COMPLIANCE_REPORT_ACCESSED = "compliance.report_accessed"


class AuditOutcome(StrEnum):
    SUCCESS = "success"
    DENIED = "denied"
    FAILED = "failed"


JsonObject = dict[str, object]


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=True,
    )
    actor: Mapped[str] = mapped_column(String(255), nullable=False, default="system")
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
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
    outcome: Mapped[AuditOutcome] = mapped_column(
        Enum(
            AuditOutcome,
            name="audit_outcome",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        default=AuditOutcome.SUCCESS,
    )
    reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    event_metadata: Mapped[JsonObject | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


Index("ix_audit_logs_created_at", AuditLog.created_at)
Index("ix_audit_logs_entity_type_entity_id", AuditLog.entity_type, AuditLog.entity_id)
Index("ix_audit_logs_action", AuditLog.action)
Index("ix_audit_logs_actor", AuditLog.actor)
Index("ix_audit_logs_organization_id_created_at", AuditLog.organization_id, AuditLog.created_at)
Index("ix_audit_logs_outcome_created_at", AuditLog.outcome, AuditLog.created_at)


@event.listens_for(AuditLog, "before_update")
@event.listens_for(AuditLog, "before_delete")
def prevent_audit_log_mutation(
    mapper: Mapper[AuditLog],
    connection: object,
    target: AuditLog,
) -> None:
    raise ValueError("Audit logs are append-only.")
