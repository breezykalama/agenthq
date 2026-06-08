"""add tenant scoping

Revision ID: 202606080004
Revises: 202606080003
Create Date: 2026-06-08
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa

from alembic import op

revision: str = "202606080004"
down_revision: str | None = "202606080003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCOPED_TABLES = [
    "agents",
    "agent_tools",
    "mcp_servers",
    "policy_rules",
    "approvals",
    "executions",
    "incidents",
]


def upgrade() -> None:
    bind = op.get_bind()
    organization_id = get_or_create_default_organization(bind)
    attach_users_without_membership(bind, organization_id)

    for table_name in SCOPED_TABLES:
        op.add_column(table_name, sa.Column("organization_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            f"fk_{table_name}_organization_id",
            table_name,
            "organizations",
            ["organization_id"],
            ["id"],
        )
        bind.execute(
            sa.text(f"UPDATE {table_name} SET organization_id = :organization_id"),
            {"organization_id": organization_id},
        )
        op.alter_column(table_name, "organization_id", nullable=False)
        op.create_index(
            f"ix_{table_name}_organization_id",
            table_name,
            ["organization_id"],
            unique=False,
        )

    op.add_column("audit_logs", sa.Column("organization_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_audit_logs_organization_id",
        "audit_logs",
        "organizations",
        ["organization_id"],
        ["id"],
    )
    bind.execute(
        sa.text("UPDATE audit_logs SET organization_id = :organization_id"),
        {"organization_id": organization_id},
    )
    op.create_index(
        "ix_audit_logs_organization_id_created_at",
        "audit_logs",
        ["organization_id", "created_at"],
        unique=False,
    )

    op.drop_index("ix_agents_unique_name_not_deleted", table_name="agents")
    op.create_index(
        "ix_agents_unique_name_not_deleted",
        "agents",
        ["organization_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index("ix_mcp_servers_unique_name_not_deleted", table_name="mcp_servers")
    op.create_index(
        "ix_mcp_servers_unique_name_not_deleted",
        "mcp_servers",
        ["organization_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index("ix_policy_rules_unique_name_not_deleted", table_name="policy_rules")
    op.create_index(
        "ix_policy_rules_unique_name_not_deleted",
        "policy_rules",
        ["organization_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_policy_rules_unique_name_not_deleted", table_name="policy_rules")
    op.create_index(
        "ix_policy_rules_unique_name_not_deleted",
        "policy_rules",
        ["name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index("ix_mcp_servers_unique_name_not_deleted", table_name="mcp_servers")
    op.create_index(
        "ix_mcp_servers_unique_name_not_deleted",
        "mcp_servers",
        ["name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index("ix_agents_unique_name_not_deleted", table_name="agents")
    op.create_index(
        "ix_agents_unique_name_not_deleted",
        "agents",
        ["name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.drop_index("ix_audit_logs_organization_id_created_at", table_name="audit_logs")
    op.drop_constraint("fk_audit_logs_organization_id", "audit_logs", type_="foreignkey")
    op.drop_column("audit_logs", "organization_id")

    for table_name in reversed(SCOPED_TABLES):
        op.drop_index(f"ix_{table_name}_organization_id", table_name=table_name)
        op.drop_constraint(
            f"fk_{table_name}_organization_id",
            table_name,
            type_="foreignkey",
        )
        op.drop_column(table_name, "organization_id")


def get_or_create_default_organization(bind: sa.Connection) -> UUID:
    existing = bind.execute(
        sa.text(
            "SELECT id FROM organizations "
            "WHERE deleted_at IS NULL ORDER BY created_at ASC LIMIT 1"
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    organization_id = uuid4()
    now = datetime.now(UTC)
    bind.execute(
        sa.text(
            "INSERT INTO organizations "
            "(id, name, slug, created_at, updated_at, deleted_at) "
            "VALUES (:id, :name, :slug, :created_at, :updated_at, NULL)"
        ),
        {
            "id": organization_id,
            "name": "Default Organization",
            "slug": "default-organization",
            "created_at": now,
            "updated_at": now,
        },
    )
    return organization_id


def attach_users_without_membership(bind: sa.Connection, organization_id: UUID) -> None:
    users = bind.execute(
        sa.text(
            "SELECT users.id, users.role::text "
            "FROM users "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM organization_memberships memberships "
            "WHERE memberships.user_id = users.id AND memberships.is_active = true"
            ")"
        )
    ).all()
    now = datetime.now(UTC)
    for user_id, role in users:
        bind.execute(
            sa.text(
                "INSERT INTO organization_memberships "
                "(id, organization_id, user_id, role, is_active, created_at, updated_at) "
                "VALUES (:id, :organization_id, :user_id, "
                "CAST(:role AS organization_membership_role), true, :created_at, :updated_at)"
            ),
            {
                "id": uuid4(),
                "organization_id": organization_id,
                "user_id": user_id,
                "role": role,
                "created_at": now,
                "updated_at": now,
            },
        )
