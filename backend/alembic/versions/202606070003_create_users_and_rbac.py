"""create users and rbac

Revision ID: 202606070003
Revises: 202606070002
Create Date: 2026-06-07 00:03:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202606070003"
down_revision: str | None = "202606070002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_role = postgresql.ENUM(
    "admin", "auditor", "operator", "agent_owner", name="user_role", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    user_role.create(bind, checkfirst=True)
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'user.created'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'user.updated'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'user.login'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'user.deactivated'")
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    bind = op.get_bind()
    user_role.drop(bind, checkfirst=True)
