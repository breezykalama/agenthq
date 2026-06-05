"""create agents table

Revision ID: 202606050001
Revises:
Create Date: 2026-06-05 00:01:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202606050001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

agent_risk_level = postgresql.ENUM(
    "low",
    "medium",
    "high",
    "critical",
    name="agent_risk_level",
    create_type=False,
)
agent_status = postgresql.ENUM(
    "draft",
    "active",
    "disabled",
    "archived",
    name="agent_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    agent_risk_level.create(bind, checkfirst=True)
    agent_status.create(bind, checkfirst=True)

    op.create_table(
        "agents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner", sa.String(length=255), nullable=False),
        sa.Column("department", sa.String(length=255), nullable=False),
        sa.Column("risk_level", agent_risk_level, nullable=False),
        sa.Column("status", agent_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agents_unique_name_not_deleted",
        "agents",
        ["name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_agents_unique_name_not_deleted", table_name="agents")
    op.drop_table("agents")

    bind = op.get_bind()
    agent_status.drop(bind, checkfirst=True)
    agent_risk_level.drop(bind, checkfirst=True)
