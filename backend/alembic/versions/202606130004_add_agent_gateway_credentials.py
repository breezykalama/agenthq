"""Add agent-scoped gateway credentials.

Revision ID: 202606130004
Revises: 202606130003
Create Date: 2026-06-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202606130004"
down_revision: str | None = "202606130003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_AUDIT_ACTIONS = (
    "agent_gateway_credential.created",
    "agent_gateway_credential.rotated",
    "agent_gateway_credential.revoked",
    "agent_gateway_credential.used",
    "agent_gateway_credential.denied",
    "mcp_gateway.auth_denied",
)


def upgrade() -> None:
    op.add_column("mcp_gateway_tokens", sa.Column("agent_id", sa.Uuid(), nullable=True))
    op.add_column(
        "mcp_gateway_tokens",
        sa.Column(
            "allowed_mcp_server_ids",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE mcp_gateway_tokens AS token
        SET agent_id = server.agent_id,
            allowed_mcp_server_ids = jsonb_build_array(token.mcp_server_id::text)
        FROM mcp_servers AS server
        WHERE server.id = token.mcp_server_id
        """
    )
    op.alter_column("mcp_gateway_tokens", "agent_id", nullable=False)
    op.alter_column("mcp_gateway_tokens", "mcp_server_id", nullable=True)
    op.alter_column("mcp_gateway_tokens", "allowed_mcp_server_ids", server_default=None)
    op.create_foreign_key(
        "fk_mcp_gateway_tokens_agent_id",
        "mcp_gateway_tokens",
        "agents",
        ["agent_id"],
        ["id"],
    )
    op.create_index(
        "ix_mcp_gateway_tokens_organization_agent",
        "mcp_gateway_tokens",
        ["organization_id", "agent_id"],
    )
    for action in NEW_AUDIT_ACTIONS:
        op.execute(f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{action}'")


def downgrade() -> None:
    op.drop_index("ix_mcp_gateway_tokens_organization_agent", table_name="mcp_gateway_tokens")
    op.drop_constraint("fk_mcp_gateway_tokens_agent_id", "mcp_gateway_tokens", type_="foreignkey")
    op.execute(
        """
        UPDATE mcp_gateway_tokens
        SET mcp_server_id = (allowed_mcp_server_ids ->> 0)::uuid
        WHERE mcp_server_id IS NULL
        """
    )
    op.alter_column("mcp_gateway_tokens", "mcp_server_id", nullable=False)
    op.drop_column("mcp_gateway_tokens", "allowed_mcp_server_ids")
    op.drop_column("mcp_gateway_tokens", "agent_id")
