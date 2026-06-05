"""create incidents table

Revision ID: 202606050009
Revises: 202606050008
Create Date: 2026-06-05 00:09:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202606050009"
down_revision: str | None = "202606050008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

incident_status = postgresql.ENUM(
    "open",
    "investigating",
    "resolved",
    "dismissed",
    name="incident_status",
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
    incident_status.create(bind, checkfirst=True)

    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'incident.created'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'incident.updated'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'incident.resolved'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'incident.dismissed'")

    op.create_table(
        "incidents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", agent_risk_level, nullable=False),
        sa.Column("status", incident_status, nullable=False),
        sa.Column("reported_by", sa.String(length=255), nullable=False),
        sa.Column("assigned_to", sa.String(length=255), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("incidents")

    bind = op.get_bind()
    incident_status.drop(bind, checkfirst=True)
