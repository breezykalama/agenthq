"""create audit logs table

Revision ID: 202606050002
Revises: 202606050001
Create Date: 2026-06-05 00:02:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202606050002"
down_revision: str | None = "202606050001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

audit_action = postgresql.ENUM(
    "agent.created",
    "agent.updated",
    "agent.deleted",
    name="audit_action",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    audit_action.create(bind, checkfirst=True)

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("action", audit_action, nullable=False),
        sa.Column("entity_type", sa.String(length=255), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")

    bind = op.get_bind()
    audit_action.drop(bind, checkfirst=True)
