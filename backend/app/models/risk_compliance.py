from datetime import date, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.agent import AgentRiskLevel, utc_now
from app.schemas.tool_governance import ToolGovernanceStatus


class PolicyCoverageStatus(StrEnum):
    COVERED = "covered"
    PARTIALLY_COVERED = "partially_covered"
    UNCOVERED = "uncovered"


class ComplianceStatus(StrEnum):
    COMPLIANT = "compliant"
    WARNING = "warning"
    NON_COMPLIANT = "non_compliant"


class AIRiskRecord(Base):
    __tablename__ = "ai_risk_register"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    tool_id: Mapped[UUID] = mapped_column(ForeignKey("agent_tools.id"), nullable=False)
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("agents.id"), nullable=False)
    mcp_server_id: Mapped[UUID] = mapped_column(ForeignKey("mcp_servers.id"), nullable=False)
    risk_level: Mapped[AgentRiskLevel] = mapped_column(
        Enum(
            AgentRiskLevel,
            name="agent_risk_level",
            values_callable=lambda enum: [item.value for item in enum],
            create_type=False,
        ),
        nullable=False,
    )
    governance_status: Mapped[ToolGovernanceStatus] = mapped_column(
        Enum(
            ToolGovernanceStatus,
            name="tool_governance_status",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    policy_coverage_status: Mapped[PolicyCoverageStatus] = mapped_column(
        Enum(
            PolicyCoverageStatus,
            name="policy_coverage_status",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    compliance_status: Mapped[ComplianceStatus] = mapped_column(
        Enum(
            ComplianceStatus,
            name="compliance_status",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    owner_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ComplianceControl(Base):
    __tablename__ = "compliance_controls"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[AgentRiskLevel] = mapped_column(
        Enum(
            AgentRiskLevel,
            name="agent_risk_level",
            values_callable=lambda enum: [item.value for item in enum],
            create_type=False,
        ),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class RiskSnapshot(Base):
    __tablename__ = "risk_snapshots"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False)
    governed_tools: Mapped[int] = mapped_column(Integer, nullable=False)
    ungoverned_tools: Mapped[int] = mapped_column(Integer, nullable=False)
    compliant_tools: Mapped[int] = mapped_column(Integer, nullable=False)
    non_compliant_tools: Mapped[int] = mapped_column(Integer, nullable=False)
    open_alerts: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


Index(
    "ix_ai_risk_register_org_tool", AIRiskRecord.organization_id, AIRiskRecord.tool_id, unique=True
)
Index(
    "ix_ai_risk_register_org_compliance",
    AIRiskRecord.organization_id,
    AIRiskRecord.compliance_status,
)
Index(
    "ix_compliance_controls_org_name",
    ComplianceControl.organization_id,
    ComplianceControl.name,
    unique=True,
)
Index("ix_risk_snapshots_org_date", RiskSnapshot.organization_id, RiskSnapshot.date, unique=True)
