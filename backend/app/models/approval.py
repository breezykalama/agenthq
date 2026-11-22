from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.agent import AgentRiskLevel, utc_now


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("agents.id"), nullable=False)
    requested_action: Mapped[str] = mapped_column(String(255), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False, default="system")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(
            ApprovalStatus,
            name="approval_status",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        default=ApprovalStatus.PENDING,
    )
    risk_level: Mapped[AgentRiskLevel] = mapped_column(
        Enum(
            AgentRiskLevel,
            name="agent_risk_level",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    approver: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Single use: an approved request authorizes at most one gateway execution attempt. Set once,
    # atomically, before the upstream call, and never cleared. The execution ID is reserved
    # before the claim and is deliberately not a foreign key: the claim is committed before the
    # execution row exists, and must survive even if that row is never written.
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_by_execution_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )


Index("ix_approvals_agent_id_requested_at", Approval.agent_id, Approval.requested_at)
Index("ix_approvals_status_requested_at", Approval.status, Approval.requested_at)
Index("ix_approvals_organization_id", Approval.organization_id)
