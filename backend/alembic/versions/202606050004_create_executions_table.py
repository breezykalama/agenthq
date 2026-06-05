"""create executions table

Revision ID: 202606050004
Revises: 202606050003
Create Date: 2026-06-05 00:04:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202606050004"
down_revision: str | None = "202606050003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

execution_status = postgresql.ENUM(
    "pending",
    "running",
    "succeeded",
    "failed",
    "blocked",
    "requires_approval",
    name="execution_status",
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
    execution_status.create(bind, checkfirst=True)

    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'execution.created'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'execution.updated'")

    op.create_table(
        "executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("action_name", sa.String(length=255), nullable=False),
        sa.Column("input_summary", sa.Text(), nullable=True),
        sa.Column("output_summary", sa.Text(), nullable=True),
        sa.Column("status", execution_status, nullable=False),
        sa.Column("risk_level", agent_risk_level, nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(12, 4), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("executions")

    bind = op.get_bind()
    execution_status.drop(bind, checkfirst=True)
