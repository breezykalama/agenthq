"""add mcp server sync fields

Revision ID: 202606070002
Revises: 202606070001
Create Date: 2026-06-07 00:02:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202606070002"
down_revision: str | None = "202606070001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'mcp_server.synced'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'mcp_server.sync_failed'")

    op.add_column("mcp_servers", sa.Column("agent_id", sa.Uuid(), nullable=True))
    op.add_column("mcp_servers", sa.Column("last_error", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_mcp_servers_agent_id_agents",
        "mcp_servers",
        "agents",
        ["agent_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_mcp_servers_agent_id_agents", "mcp_servers", type_="foreignkey")
    op.drop_column("mcp_servers", "last_error")
    op.drop_column("mcp_servers", "agent_id")
