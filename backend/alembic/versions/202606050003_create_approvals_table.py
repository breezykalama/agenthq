"""create approvals table

Revision ID: 202606050003
Revises: 202606050002
Create Date: 2026-06-05 00:03:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202606050003"
down_revision: str | None = "202606050002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

approval_status = postgresql.ENUM(
    "pending",
    "approved",
    "rejected",
    "cancelled",
    name="approval_status",
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
    approval_status.create(bind, checkfirst=True)

    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'approval.created'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'approval.approved'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'approval.rejected'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'approval.cancelled'")

    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("requested_action", sa.String(length=255), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", approval_status, nullable=False),
        sa.Column("risk_level", agent_risk_level, nullable=False),
        sa.Column("approver", sa.String(length=255), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("approvals")

    bind = op.get_bind()
    approval_status.drop(bind, checkfirst=True)
