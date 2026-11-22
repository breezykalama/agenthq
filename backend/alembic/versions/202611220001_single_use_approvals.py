"""Make approvals single use.

Revision ID: 202611220001
Revises: 202611170001
Create Date: 2026-11-22

Adds ``approvals.consumed_at`` and ``approvals.consumed_by_execution_id`` and the
``approval.consumed`` audit action. Purely additive: no table, column or row is removed.

Transition strategy (fail closed): before this revision an approved request could be reused
indefinitely, and nothing records whether a given approval has already authorized a call. Every
approval that is ``approved`` when this revision runs is therefore marked consumed, linked to its
earliest recorded execution when one exists. A new approval is needed for any further call.
Pending, rejected and cancelled approvals are unchanged.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202611220001"
down_revision: str | None = "202611170001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'approval.consumed'")
    op.add_column("approvals", sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "approvals",
        sa.Column("consumed_by_execution_id", sa.Uuid(), nullable=True),
    )
    op.execute(
        """
        UPDATE approvals
        SET consumed_at = now(),
            consumed_by_execution_id = (
                SELECT e.id FROM executions e
                WHERE e.approval_id = approvals.id
                ORDER BY e.created_at, e.id
                LIMIT 1
            )
        WHERE status = 'approved' AND consumed_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("approvals", "consumed_by_execution_id")
    op.drop_column("approvals", "consumed_at")
