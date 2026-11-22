"""Reserve gateway idempotency keys before upstream dispatch.

Revision ID: 202611220002
Revises: 202611220001
Create Date: 2026-11-22

``mcp_gateway_call_records`` gains ``state`` (``in_progress`` or ``completed``) and
``request_hash`` (SHA-256 of the canonical request), and ``execution_id`` and
``response_payload`` become nullable while a reservation is in progress. The existing unique
index on (gateway token, tool, idempotency key) is unchanged and now arbitrates reservations.

Existing rows are preserved: they become ``completed`` with no fingerprint, keep their
execution and stored response, and keep replaying exactly as before.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202611220002"
down_revision: str | None = "202611220001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_gateway_call_records",
        sa.Column(
            "state",
            sa.String(length=16),
            nullable=False,
            server_default="completed",
        ),
    )
    op.add_column(
        "mcp_gateway_call_records",
        sa.Column("request_hash", sa.String(length=64), nullable=True),
    )
    op.alter_column("mcp_gateway_call_records", "execution_id", nullable=True)
    op.alter_column("mcp_gateway_call_records", "response_payload", nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM mcp_gateway_call_records WHERE state <> 'completed'")
    op.alter_column("mcp_gateway_call_records", "response_payload", nullable=False)
    op.alter_column("mcp_gateway_call_records", "execution_id", nullable=False)
    op.drop_column("mcp_gateway_call_records", "request_hash")
    op.drop_column("mcp_gateway_call_records", "state")
