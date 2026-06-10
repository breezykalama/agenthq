"""Harden audit logs with standardized security event fields.

Revision ID: 202606100002
Revises: 202606100001
Create Date: 2026-06-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202606100002"
down_revision: str | None = "202606100001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_AUDIT_ACTIONS = (
    "execution.started",
    "execution.completed",
    "execution.failed",
    "auth.login_failed",
    "security.access_denied",
    "security.cross_org_access_denied",
    "security.inactive_membership_denied",
    "security.rate_limited",
    "compliance.report_accessed",
)

audit_outcome = postgresql.ENUM(
    "success",
    "denied",
    "failed",
    name="audit_outcome",
    create_type=False,
)


def upgrade() -> None:
    for action in NEW_AUDIT_ACTIONS:
        op.execute(f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{action}'")

    bind = op.get_bind()
    audit_outcome.create(bind, checkfirst=True)
    op.add_column("audit_logs", sa.Column("actor_user_id", sa.Uuid(), nullable=True))
    op.add_column("audit_logs", sa.Column("actor_role", sa.String(length=50), nullable=True))
    op.add_column(
        "audit_logs",
        sa.Column(
            "outcome",
            audit_outcome,
            server_default="success",
            nullable=False,
        ),
    )
    op.add_column("audit_logs", sa.Column("reason", sa.String(length=1000), nullable=True))
    op.add_column("audit_logs", sa.Column("request_id", sa.String(length=255), nullable=True))
    op.add_column("audit_logs", sa.Column("ip_address", sa.String(length=64), nullable=True))
    op.add_column("audit_logs", sa.Column("user_agent", sa.String(length=512), nullable=True))
    op.add_column("audit_logs", sa.Column("metadata", sa.JSON(), nullable=True))
    op.create_foreign_key(
        "fk_audit_logs_actor_user_id",
        "audit_logs",
        "users",
        ["actor_user_id"],
        ["id"],
    )
    op.create_index(
        "ix_audit_logs_outcome_created_at",
        "audit_logs",
        ["outcome", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_outcome_created_at", table_name="audit_logs")
    op.drop_constraint("fk_audit_logs_actor_user_id", "audit_logs", type_="foreignkey")
    for column_name in (
        "metadata",
        "user_agent",
        "ip_address",
        "request_id",
        "reason",
        "outcome",
        "actor_role",
        "actor_user_id",
    ):
        op.drop_column("audit_logs", column_name)

    bind = op.get_bind()
    audit_outcome.drop(bind, checkfirst=True)
