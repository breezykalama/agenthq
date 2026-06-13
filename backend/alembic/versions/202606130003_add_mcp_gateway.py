"""Add MCP governance gateway.

Revision ID: 202606130003
Revises: 202606130002
Create Date: 2026-06-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202606130003"
down_revision: str | None = "202606130002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

token_status = postgresql.ENUM(
    "active",
    "revoked",
    name="mcp_gateway_token_status",
    create_type=False,
)
NEW_AUDIT_ACTIONS = (
    "mcp_gateway.token_created",
    "mcp_gateway.token_revoked",
    "mcp_gateway.token_rotated",
    "mcp_gateway.tools_listed",
    "mcp_gateway.call_requested",
    "mcp_gateway.call_blocked",
    "mcp_gateway.call_requires_approval",
    "mcp_gateway.call_succeeded",
    "mcp_gateway.call_failed",
)


def upgrade() -> None:
    bind = op.get_bind()
    token_status.create(bind, checkfirst=True)
    for action in NEW_AUDIT_ACTIONS:
        op.execute(f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{action}'")
    op.create_table(
        "mcp_gateway_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("mcp_server_id", sa.Uuid(), sa.ForeignKey("mcp_servers.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("status", token_status, server_default="active", nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_mcp_gateway_tokens_organization_server",
        "mcp_gateway_tokens",
        ["organization_id", "mcp_server_id"],
    )
    op.create_table(
        "mcp_gateway_call_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column(
            "gateway_token_id",
            sa.Uuid(),
            sa.ForeignKey("mcp_gateway_tokens.id"),
            nullable=False,
        ),
        sa.Column("tool_id", sa.Uuid(), sa.ForeignKey("agent_tools.id"), nullable=False),
        sa.Column("execution_id", sa.Uuid(), sa.ForeignKey("executions.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("response_payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_mcp_gateway_call_records_idempotency",
        "mcp_gateway_call_records",
        ["gateway_token_id", "tool_id", "idempotency_key"],
        unique=True,
    )
    for table in ("mcp_gateway_tokens", "mcp_gateway_call_records"):
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                    REVOKE ALL PRIVILEGES ON TABLE public."{table}" FROM anon;
                END IF;
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                    REVOKE ALL PRIVILEGES ON TABLE public."{table}" FROM authenticated;
                END IF;
            END
            $$;
            """
        )


def downgrade() -> None:
    op.drop_table("mcp_gateway_call_records")
    op.drop_table("mcp_gateway_tokens")
    token_status.drop(op.get_bind(), checkfirst=True)
