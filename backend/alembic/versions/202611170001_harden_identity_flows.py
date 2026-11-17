"""Harden identity flows: session versioning, verification enforcement, email outbox.

Revision ID: 202611170001
Revises: 202606270001
Create Date: 2026-11-17

Transition strategy:
- ``users.auth_version`` defaults to 0. Access tokens issued before this revision carry no
  version claim and are treated as version 0, so nobody is signed out by the deploy.
- ``users.email_verification_required`` defaults to false, so every existing account (including
  existing unverified administrators) is grandfathered. Only administrators created by
  organization bootstrap after this release are flagged.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202611170001"
down_revision: str | None = "202606270001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUDIT_ACTIONS = (
    "auth.email_verification_requested",
    "auth.password_reset_email_sent",
    "auth.password_reset_email_failed",
)


def upgrade() -> None:
    for action in AUDIT_ACTIONS:
        op.execute(f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{action}'")

    op.add_column(
        "users",
        sa.Column(
            "email_verification_required",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("auth_version", sa.Integer(), server_default="0", nullable=False),
    )

    op.create_table(
        "email_outbox",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("token_id", sa.Uuid(), nullable=False),
        sa.Column("token_nonce", sa.String(64), nullable=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=True
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(64), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("kind", "token_id", name="uq_email_outbox_kind_token"),
        sa.CheckConstraint(
            "kind IN ('email_verification', 'password_reset', 'organization_invite')",
            name="ck_email_outbox_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'sent', 'failed', 'cancelled')",
            name="ck_email_outbox_status",
        ),
    )
    op.create_index(
        "ix_email_outbox_status_next_attempt_at",
        "email_outbox",
        ["status", "next_attempt_at"],
    )

    op.execute('ALTER TABLE public."email_outbox" ENABLE ROW LEVEL SECURITY')
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL PRIVILEGES ON TABLE public."email_outbox" FROM anon;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                REVOKE ALL PRIVILEGES ON TABLE public."email_outbox" FROM authenticated;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_email_outbox_status_next_attempt_at", table_name="email_outbox")
    op.drop_table("email_outbox")
    op.drop_column("users", "auth_version")
    op.drop_column("users", "email_verification_required")
