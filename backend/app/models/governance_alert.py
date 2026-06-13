from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.agent import utc_now


class GovernanceAlertType(StrEnum):
    NEW_TOOL_DISCOVERED = "new_tool_discovered"
    TOOL_REMOVED = "tool_removed"
    SCHEMA_CHANGED = "schema_changed"
    DESCRIPTION_CHANGED = "description_changed"
    HIGH_RISK_UNREVIEWED = "high_risk_unreviewed"
    UNGOVERNED_TOOL = "ungoverned_tool"
    POLICY_COVERAGE_LOST = "policy_coverage_lost"
    COMPLIANCE_NON_COMPLIANT = "compliance_non_compliant"
    CRITICAL_POLICY_COVERAGE_LOST = "critical_policy_coverage_lost"
    CRITICAL_TOOL_UNREVIEWED = "critical_tool_unreviewed"


class GovernanceAlertSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class GovernanceAlertStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class GovernanceAlert(Base):
    __tablename__ = "governance_alerts"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    alert_type: Mapped[GovernanceAlertType] = mapped_column(
        Enum(
            GovernanceAlertType,
            name="governance_alert_type",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    severity: Mapped[GovernanceAlertSeverity] = mapped_column(
        Enum(
            GovernanceAlertSeverity,
            name="governance_alert_severity",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    status: Mapped[GovernanceAlertStatus] = mapped_column(
        Enum(
            GovernanceAlertStatus,
            name="governance_alert_status",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        default=GovernanceAlertStatus.OPEN,
    )
    agent_id: Mapped[UUID | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    tool_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_tools.id"), nullable=True)
    mcp_server_id: Mapped[UUID | None] = mapped_column(ForeignKey("mcp_servers.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    alert_metadata: Mapped[dict[str, object] | None] = mapped_column(
        "metadata",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )
    acknowledged_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


Index(
    "ix_governance_alerts_organization_status",
    GovernanceAlert.organization_id,
    GovernanceAlert.status,
)
Index(
    "ix_governance_alerts_tool_type",
    GovernanceAlert.tool_id,
    GovernanceAlert.alert_type,
)
Index("ix_governance_alerts_created_at", GovernanceAlert.created_at)
