"""Add email verification and password reset identity flows.

Revision ID: 202606270001
Revises: 202606130005
Create Date: 2026-06-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202606270001"
down_revision: str | None = "202606130005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

verification_status = postgresql.ENUM(
    "pending",
    "used",
    "expired",
    "revoked",
    name="email_verification_token_status",
    create_type=False,
)
reset_status = postgresql.ENUM(
    "pending",
    "used",
    "expired",
    name="password_reset_token_status",
    create_type=False,
)

AUDIT_ACTIONS = (
    "auth.email_verification_sent",
    "auth.email_verified",
    "auth.email_verification_failed",
    "auth.password_reset_requested",
    "auth.password_reset_completed",
    "auth.password_reset_failed",
    "organization_invite.email_sent",
    "organization_invite.email_failed",
)


def upgrade() -> None:
    bind = op.get_bind()
    verification_status.create(bind, checkfirst=True)
    reset_status.create(bind, checkfirst=True)
    for action in AUDIT_ACTIONS:
        op.execute(f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{action}'")

    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "email_verification_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("status", verification_status, server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_email_verification_tokens_user_id", "email_verification_tokens", ["user_id"]
    )
    op.create_index(
        "ix_email_verification_tokens_status", "email_verification_tokens", ["status"]
    )
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("status", reset_status, server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])
    op.create_index("ix_password_reset_tokens_status", "password_reset_tokens", ["status"])

    for table in ("email_verification_tokens", "password_reset_tokens"):
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
    op.drop_table("password_reset_tokens")
    op.drop_table("email_verification_tokens")
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "email_verified")
    reset_status.drop(op.get_bind(), checkfirst=True)
    verification_status.drop(op.get_bind(), checkfirst=True)
