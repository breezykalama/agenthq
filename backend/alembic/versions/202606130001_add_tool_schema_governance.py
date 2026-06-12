"""Add MCP tool schema governance.

Revision ID: 202606130001
Revises: 202606120001
Create Date: 2026-06-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202606130001"
down_revision: str | None = "202606120001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_AUDIT_ACTIONS = (
    "mcp_tool.discovered",
    "mcp_tool.removed",
    "mcp_tool.schema_changed",
    "mcp_tool.description_changed",
    "mcp_tool.reviewed",
    "mcp_tool.risk_changed",
    "mcp_tool.permission_changed",
)


def upgrade() -> None:
    for action in NEW_AUDIT_ACTIONS:
        op.execute(f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{action}'")

    op.add_column(
        "agent_tools",
        sa.Column("discovered_from_mcp_server_id", sa.Uuid(), nullable=True),
    )
    op.add_column("agent_tools", sa.Column("input_schema", postgresql.JSONB(), nullable=True))
    op.add_column("agent_tools", sa.Column("output_schema", postgresql.JSONB(), nullable=True))
    op.add_column("agent_tools", sa.Column("schema_hash", sa.String(length=64), nullable=True))
    op.add_column("agent_tools", sa.Column("schema_version", sa.Integer(), nullable=True))
    op.add_column(
        "agent_tools",
        sa.Column("schema_last_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("agent_tools", sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True))
    op.add_column(
        "agent_tools",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_tools_discovered_from_mcp_server_id",
        "agent_tools",
        "mcp_servers",
        ["discovered_from_mcp_server_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_agent_tools_reviewed_by_user_id",
        "agent_tools",
        "users",
        ["reviewed_by_user_id"],
        ["id"],
    )
    op.create_index(
        "ix_agent_tools_discovered_from_mcp_server_id",
        "agent_tools",
        ["discovered_from_mcp_server_id"],
    )
    op.create_index("ix_agent_tools_reviewed_at", "agent_tools", ["reviewed_at"])
    op.execute(
        """
        UPDATE agent_tools AS tool
        SET discovered_from_mcp_server_id = server.id
        FROM mcp_servers AS server
        WHERE tool.organization_id = server.organization_id
          AND tool.agent_id = server.agent_id
          AND tool.deleted_at IS NULL
          AND server.deleted_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_agent_tools_reviewed_at", table_name="agent_tools")
    op.drop_index("ix_agent_tools_discovered_from_mcp_server_id", table_name="agent_tools")
    op.drop_constraint(
        "fk_agent_tools_reviewed_by_user_id",
        "agent_tools",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_agent_tools_discovered_from_mcp_server_id",
        "agent_tools",
        type_="foreignkey",
    )
    for column_name in (
        "reviewed_at",
        "reviewed_by_user_id",
        "schema_last_updated_at",
        "schema_version",
        "schema_hash",
        "output_schema",
        "input_schema",
        "discovered_from_mcp_server_id",
    ):
        op.drop_column("agent_tools", column_name)
