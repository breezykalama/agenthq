"""Add governance alerts and monitoring.

Revision ID: 202606130002
Revises: 202606130001
Create Date: 2026-06-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202606130002"
down_revision: str | None = "202606130001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

alert_type = postgresql.ENUM(
    "new_tool_discovered",
    "tool_removed",
    "schema_changed",
    "description_changed",
    "high_risk_unreviewed",
    "ungoverned_tool",
    "policy_coverage_lost",
    name="governance_alert_type",
    create_type=False,
)
alert_severity = postgresql.ENUM(
    "low", "medium", "high", "critical", name="governance_alert_severity", create_type=False
)
alert_status = postgresql.ENUM(
    "open", "acknowledged", "resolved", name="governance_alert_status", create_type=False
)
NEW_AUDIT_ACTIONS = (
    "governance_alert.created",
    "governance_alert.acknowledged",
    "governance_alert.resolved",
    "governance_alert.reopened",
)


def upgrade() -> None:
    bind = op.get_bind()
    alert_type.create(bind, checkfirst=True)
    alert_severity.create(bind, checkfirst=True)
    alert_status.create(bind, checkfirst=True)
    for action in NEW_AUDIT_ACTIONS:
        op.execute(f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{action}'")
    op.create_table(
        "governance_alerts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("alert_type", alert_type, nullable=False),
        sa.Column("severity", alert_severity, nullable=False),
        sa.Column("status", alert_status, server_default="open", nullable=False),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id")),
        sa.Column("tool_id", sa.Uuid(), sa.ForeignKey("agent_tools.id")),
        sa.Column("mcp_server_id", sa.Uuid(), sa.ForeignKey("mcp_servers.id")),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB()),
        sa.Column("acknowledged_by_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_by_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_governance_alerts_organization_status",
        "governance_alerts",
        ["organization_id", "status"],
    )
    op.create_index(
        "ix_governance_alerts_tool_type",
        "governance_alerts",
        ["tool_id", "alert_type"],
    )
    op.create_index("ix_governance_alerts_created_at", "governance_alerts", ["created_at"])
    op.execute('ALTER TABLE public."governance_alerts" ENABLE ROW LEVEL SECURITY')
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL PRIVILEGES ON TABLE public."governance_alerts" FROM anon;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                REVOKE ALL PRIVILEGES ON TABLE public."governance_alerts" FROM authenticated;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.drop_table("governance_alerts")
    bind = op.get_bind()
    alert_status.drop(bind, checkfirst=True)
    alert_severity.drop(bind, checkfirst=True)
    alert_type.drop(bind, checkfirst=True)
