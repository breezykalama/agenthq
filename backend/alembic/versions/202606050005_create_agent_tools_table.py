"""create agent tools table

Revision ID: 202606050005
Revises: 202606050004
Create Date: 2026-06-05 00:05:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202606050005"
down_revision: str | None = "202606050004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

agent_tool_permission = postgresql.ENUM(
    "read",
    "write",
    "execute",
    "admin",
    name="agent_tool_permission",
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
    agent_tool_permission.create(bind, checkfirst=True)

    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'agent_tool.created'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'agent_tool.updated'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'agent_tool.deleted'")

    op.create_table(
        "agent_tools",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("permission", agent_tool_permission, nullable=False),
        sa.Column("risk_level", agent_risk_level, nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_tools_unique_agent_name_not_deleted",
        "agent_tools",
        ["agent_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_agent_tools_unique_agent_name_not_deleted", table_name="agent_tools")
    op.drop_table("agent_tools")

    bind = op.get_bind()
    agent_tool_permission.drop(bind, checkfirst=True)
