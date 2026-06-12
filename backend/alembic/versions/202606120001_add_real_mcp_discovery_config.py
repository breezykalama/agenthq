"""Add real MCP discovery configuration.

Revision ID: 202606120001
Revises: 202606100002
Create Date: 2026-06-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202606120001"
down_revision: str | None = "202606100002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

mcp_transport_type = postgresql.ENUM(
    "streamable_http",
    "sse",
    name="mcp_transport_type",
    create_type=False,
)
mcp_auth_type = postgresql.ENUM(
    "none",
    "bearer",
    "api_key",
    name="mcp_auth_type",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    mcp_transport_type.create(bind, checkfirst=True)
    mcp_auth_type.create(bind, checkfirst=True)

    op.add_column(
        "mcp_servers",
        sa.Column(
            "transport_type",
            mcp_transport_type,
            server_default="streamable_http",
            nullable=False,
        ),
    )
    op.add_column(
        "mcp_servers",
        sa.Column(
            "auth_type",
            mcp_auth_type,
            server_default="none",
            nullable=False,
        ),
    )
    op.add_column("mcp_servers", sa.Column("auth_secret_ref", sa.String(length=255)))
    op.add_column(
        "mcp_servers",
        sa.Column("request_timeout_seconds", sa.Integer(), server_default="30", nullable=False),
    )
    op.add_column(
        "mcp_servers",
        sa.Column("connect_timeout_seconds", sa.Integer(), server_default="10", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("mcp_servers", "connect_timeout_seconds")
    op.drop_column("mcp_servers", "request_timeout_seconds")
    op.drop_column("mcp_servers", "auth_secret_ref")
    op.drop_column("mcp_servers", "auth_type")
    op.drop_column("mcp_servers", "transport_type")

    bind = op.get_bind()
    mcp_auth_type.drop(bind, checkfirst=True)
    mcp_transport_type.drop(bind, checkfirst=True)
