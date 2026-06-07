"""create mcp servers table

Revision ID: 202606070001
Revises: 202606050009
Create Date: 2026-06-07 00:01:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202606070001"
down_revision: str | None = "202606050009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

mcp_server_status = postgresql.ENUM(
    "connected",
    "disconnected",
    "error",
    name="mcp_server_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    mcp_server_status.create(bind, checkfirst=True)

    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'mcp_server.created'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'mcp_server.updated'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'mcp_server.deleted'")

    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("server_url", sa.String(length=2048), nullable=False),
        sa.Column("status", mcp_server_status, nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mcp_servers_unique_name_not_deleted",
        "mcp_servers",
        ["name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_mcp_servers_unique_name_not_deleted", table_name="mcp_servers")
    op.drop_table("mcp_servers")

    bind = op.get_bind()
    mcp_server_status.drop(bind, checkfirst=True)
