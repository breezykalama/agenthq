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


Index("ix_approvals_agent_id_requested_at", Approval.agent_id, Approval.requested_at)
Index("ix_approvals_status_requested_at", Approval.status, Approval.requested_at)
