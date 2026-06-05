"""add policy decision audit action

Revision ID: 202606050007
Revises: 202606050006
Create Date: 2026-06-05 00:07:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202606050007"
down_revision: str | None = "202606050006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'policy_decision.evaluated'")


def downgrade() -> None:
    pass
