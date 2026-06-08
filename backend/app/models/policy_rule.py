from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.agent import AgentRiskLevel, utc_now


class PolicyRuleScope(StrEnum):
    GLOBAL = "global"
    AGENT = "agent"
    TOOL = "tool"


class PolicyRuleEffect(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    BLOCK = "block"


class PolicyRule(Base):
    __tablename__ = "policy_rules"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope: Mapped[PolicyRuleScope] = mapped_column(
        Enum(
            PolicyRuleScope,
            name="policy_rule_scope",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    agent_id: Mapped[UUID | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    tool_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_tools.id"), nullable=True)
    risk_level: Mapped[AgentRiskLevel] = mapped_column(
        Enum(
            AgentRiskLevel,
            name="agent_risk_level",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    effect: Mapped[PolicyRuleEffect] = mapped_column(
        Enum(
            PolicyRuleEffect,
            name="policy_rule_effect",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index(
    "ix_policy_rules_unique_name_not_deleted",
    PolicyRule.name,
    unique=True,
    postgresql_where=PolicyRule.deleted_at.is_(None),
    sqlite_where=PolicyRule.deleted_at.is_(None),
)
Index(
    "ix_policy_rules_scope_agent_id_tool_id_priority",
    PolicyRule.scope,
    PolicyRule.agent_id,
    PolicyRule.tool_id,
    PolicyRule.priority,
)
