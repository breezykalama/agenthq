"""add query performance indexes

Revision ID: 202606080001
Revises: 202606070003
Create Date: 2026-06-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202606080001"
down_revision: str | None = "202606070003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"], unique=False)
    op.create_index(
        "ix_audit_logs_entity_type_entity_id",
        "audit_logs",
        ["entity_type", "entity_id"],
        unique=False,
    )
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"], unique=False)
    op.create_index("ix_audit_logs_actor", "audit_logs", ["actor"], unique=False)

    op.create_index("ix_executions_created_at", "executions", ["created_at"], unique=False)
    op.create_index(
        "ix_executions_agent_id_created_at",
        "executions",
        ["agent_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_executions_status_created_at",
        "executions",
        ["status", "created_at"],
        unique=False,
    )

    op.create_index("ix_incidents_created_at", "incidents", ["created_at"], unique=False)
    op.create_index(
        "ix_incidents_agent_id_created_at",
        "incidents",
        ["agent_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_incidents_status_created_at",
        "incidents",
        ["status", "created_at"],
        unique=False,
    )

    op.create_index(
        "ix_approvals_agent_id_requested_at",
        "approvals",
        ["agent_id", "requested_at"],
        unique=False,
    )
    op.create_index(
        "ix_approvals_status_requested_at",
        "approvals",
        ["status", "requested_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_tools_agent_id_created_at",
        "agent_tools",
        ["agent_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_policy_rules_scope_agent_id_tool_id_priority",
        "policy_rules",
        ["scope", "agent_id", "tool_id", "priority"],
        unique=False,
    )
    op.create_index("ix_mcp_servers_status", "mcp_servers", ["status"], unique=False)
    op.create_index("ix_mcp_servers_agent_id", "mcp_servers", ["agent_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_mcp_servers_agent_id", table_name="mcp_servers")
    op.drop_index("ix_mcp_servers_status", table_name="mcp_servers")
    op.drop_index(
        "ix_policy_rules_scope_agent_id_tool_id_priority",
        table_name="policy_rules",
    )
    op.drop_index("ix_agent_tools_agent_id_created_at", table_name="agent_tools")
    op.drop_index("ix_approvals_status_requested_at", table_name="approvals")
    op.drop_index("ix_approvals_agent_id_requested_at", table_name="approvals")
    op.drop_index("ix_incidents_status_created_at", table_name="incidents")
    op.drop_index("ix_incidents_agent_id_created_at", table_name="incidents")
    op.drop_index("ix_incidents_created_at", table_name="incidents")
    op.drop_index("ix_executions_status_created_at", table_name="executions")
    op.drop_index("ix_executions_agent_id_created_at", table_name="executions")
    op.drop_index("ix_executions_created_at", table_name="executions")
    op.drop_index("ix_audit_logs_actor", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_entity_type_entity_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
