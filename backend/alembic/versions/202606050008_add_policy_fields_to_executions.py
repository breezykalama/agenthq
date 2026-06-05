"""add policy fields to executions

Revision ID: 202606050008
Revises: 202606050007
Create Date: 2026-06-05 00:08:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202606050008"
down_revision: str | None = "202606050007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

execution_policy_decision = postgresql.ENUM(
    "allow",
    "require_approval",
    "block",
    name="execution_policy_decision",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    execution_policy_decision.create(bind, checkfirst=True)

    op.add_column("executions", sa.Column("tool_id", sa.Uuid(), nullable=True))
    op.add_column(
        "executions",
        sa.Column("policy_decision", execution_policy_decision, nullable=True),
    )
    op.add_column("executions", sa.Column("policy_decision_reason", sa.Text(), nullable=True))
    op.add_column("executions", sa.Column("policy_rule_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_executions_tool_id_agent_tools",
        "executions",
        "agent_tools",
        ["tool_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_executions_policy_rule_id_policy_rules",
        "executions",
        "policy_rules",
        ["policy_rule_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_executions_policy_rule_id_policy_rules",
        "executions",
        type_="foreignkey",
    )
    op.drop_constraint("fk_executions_tool_id_agent_tools", "executions", type_="foreignkey")
    op.drop_column("executions", "policy_rule_id")
    op.drop_column("executions", "policy_decision_reason")
    op.drop_column("executions", "policy_decision")
    op.drop_column("executions", "tool_id")

    bind = op.get_bind()
    execution_policy_decision.drop(bind, checkfirst=True)
