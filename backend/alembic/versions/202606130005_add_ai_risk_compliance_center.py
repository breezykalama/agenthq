"""Add AI risk and compliance center.

Revision ID: 202606130005
Revises: 202606130004
Create Date: 2026-06-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202606130005"
down_revision: str | None = "202606130004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

governance_status = postgresql.ENUM(
    "unreviewed", "reviewed", "governed", name="tool_governance_status", create_type=False
)
coverage_status = postgresql.ENUM(
    "covered",
    "partially_covered",
    "uncovered",
    name="policy_coverage_status",
    create_type=False,
)
compliance_status = postgresql.ENUM(
    "compliant", "warning", "non_compliant", name="compliance_status", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    governance_status.create(bind, checkfirst=True)
    coverage_status.create(bind, checkfirst=True)
    compliance_status.create(bind, checkfirst=True)
    for action in ("compliance_control.created",):
        op.execute(f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{action}'")
    for alert_type in (
        "compliance_non_compliant",
        "critical_policy_coverage_lost",
        "critical_tool_unreviewed",
    ):
        op.execute(f"ALTER TYPE governance_alert_type ADD VALUE IF NOT EXISTS '{alert_type}'")

    op.create_table(
        "ai_risk_register",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("tool_id", sa.Uuid(), sa.ForeignKey("agent_tools.id"), nullable=False),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("mcp_server_id", sa.Uuid(), sa.ForeignKey("mcp_servers.id"), nullable=False),
        sa.Column(
            "risk_level",
            postgresql.ENUM(name="agent_risk_level", create_type=False),
            nullable=False,
        ),
        sa.Column("governance_status", governance_status, nullable=False),
        sa.Column("policy_coverage_status", coverage_status, nullable=False),
        sa.Column("compliance_status", compliance_status, nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_ai_risk_register_org_tool",
        "ai_risk_register",
        ["organization_id", "tool_id"],
        unique=True,
    )
    op.create_index(
        "ix_ai_risk_register_org_compliance",
        "ai_risk_register",
        ["organization_id", "compliance_status"],
    )
    op.create_table(
        "compliance_controls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "severity", postgresql.ENUM(name="agent_risk_level", create_type=False), nullable=False
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_compliance_controls_org_name",
        "compliance_controls",
        ["organization_id", "name"],
        unique=True,
    )
    op.create_table(
        "risk_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=False),
        sa.Column("governed_tools", sa.Integer(), nullable=False),
        sa.Column("ungoverned_tools", sa.Integer(), nullable=False),
        sa.Column("compliant_tools", sa.Integer(), nullable=False),
        sa.Column("non_compliant_tools", sa.Integer(), nullable=False),
        sa.Column("open_alerts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_risk_snapshots_org_date", "risk_snapshots", ["organization_id", "date"], unique=True
    )
    for table in ("ai_risk_register", "compliance_controls", "risk_snapshots"):
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
    op.drop_table("risk_snapshots")
    op.drop_table("compliance_controls")
    op.drop_table("ai_risk_register")
    compliance_status.drop(op.get_bind(), checkfirst=True)
    coverage_status.drop(op.get_bind(), checkfirst=True)
    governance_status.drop(op.get_bind(), checkfirst=True)
