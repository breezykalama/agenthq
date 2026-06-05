"""create policy rules table

Revision ID: 202606050006
Revises: 202606050005
Create Date: 2026-06-05 00:06:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202606050006"
down_revision: str | None = "202606050005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

policy_rule_scope = postgresql.ENUM(
    "global",
    "agent",
    "tool",
    name="policy_rule_scope",
    create_type=False,
)
policy_rule_effect = postgresql.ENUM(
    "allow",
    "require_approval",
    "block",
    name="policy_rule_effect",
    create_type=False,
)
agent_risk_level = postgresql.ENUM(
    "low",
    "medium",
    "high",
    "critical",
    name="agent_risk_level",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    policy_rule_scope.create(bind, checkfirst=True)
    policy_rule_effect.create(bind, checkfirst=True)

    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'policy_rule.created'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'policy_rule.updated'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'policy_rule.deleted'")

    op.create_table(
        "policy_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scope", policy_rule_scope, nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("tool_id", sa.Uuid(), nullable=True),
        sa.Column("risk_level", agent_risk_level, nullable=False),
        sa.Column("effect", policy_rule_effect, nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["tool_id"], ["agent_tools.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_policy_rules_unique_name_not_deleted",
        "policy_rules",
        ["name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_policy_rules_unique_name_not_deleted", table_name="policy_rules")
    op.drop_table("policy_rules")

    bind = op.get_bind()
    policy_rule_effect.drop(bind, checkfirst=True)
    policy_rule_scope.drop(bind, checkfirst=True)
