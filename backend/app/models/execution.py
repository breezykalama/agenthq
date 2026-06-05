from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.agent import AgentRiskLevel, utc_now
from app.models.policy_rule import PolicyRuleEffect


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    REQUIRES_APPROVAL = "requires_approval"


class Execution(Base):
    __tablename__ = "executions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("agents.id"), nullable=False)
    action_name: Mapped[str] = mapped_column(String(255), nullable=False)
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ExecutionStatus] = mapped_column(
        Enum(
            ExecutionStatus,
            name="execution_status",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        default=ExecutionStatus.PENDING,
    )
    risk_level: Mapped[AgentRiskLevel] = mapped_column(
        Enum(
            AgentRiskLevel,
            name="agent_risk_level",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    tool_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_tools.id"), nullable=True)
    approval_id: Mapped[UUID | None] = mapped_column(ForeignKey("approvals.id"), nullable=True)
    policy_decision: Mapped[PolicyRuleEffect | None] = mapped_column(
        Enum(
            PolicyRuleEffect,
            name="execution_policy_decision",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=True,
    )
    policy_decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    policy_rule_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("policy_rules.id"),
        nullable=True,
    )
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
