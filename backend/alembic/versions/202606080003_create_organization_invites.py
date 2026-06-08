"""create organization invites

Revision ID: 202606080003
Revises: 202606080002
Create Date: 2026-06-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202606080003"
down_revision: str | None = "202606080002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

invite_role = postgresql.ENUM(
    "admin",
    "auditor",
    "operator",
    "agent_owner",
    name="organization_invite_role",
    create_type=False,
)
invite_status = postgresql.ENUM(
    "pending",
    "accepted",
    "expired",
    "revoked",
    name="organization_invite_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    invite_role.create(bind, checkfirst=True)
    invite_status.create(bind, checkfirst=True)
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'organization_invite.created'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'organization_invite.accepted'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'organization_invite.revoked'")
    op.create_table(
        "organization_invites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("role", invite_role, nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", invite_status, nullable=False),
        sa.Column("invited_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_organization_invites_token_hash",
        "organization_invites",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_organization_invites_organization_id",
        "organization_invites",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_organization_invites_email",
        "organization_invites",
        ["email"],
        unique=False,
    )
    op.create_index(
        "ix_organization_invites_status",
        "organization_invites",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_organization_invites_unique_pending_email",
        "organization_invites",
        ["organization_id", "email"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_organization_invites_unique_pending_email",
        table_name="organization_invites",
    )
    op.drop_index("ix_organization_invites_status", table_name="organization_invites")
    op.drop_index("ix_organization_invites_email", table_name="organization_invites")
    op.drop_index(
        "ix_organization_invites_organization_id",
        table_name="organization_invites",
    )
    op.drop_index("ix_organization_invites_token_hash", table_name="organization_invites")
    op.drop_table("organization_invites")
    bind = op.get_bind()
    invite_status.drop(bind, checkfirst=True)
    invite_role.drop(bind, checkfirst=True)
