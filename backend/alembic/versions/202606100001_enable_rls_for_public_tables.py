"""Enable RLS and remove direct client access from public tables.

Revision ID: 202606100001
Revises: 202606080004
Create Date: 2026-06-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202606100001"
down_revision: str | None = "202606080004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PUBLIC_TABLES = (
    "agent_tools",
    "agents",
    "alembic_version",
    "approvals",
    "audit_logs",
    "executions",
    "incidents",
    "mcp_servers",
    "organization_invites",
    "organization_memberships",
    "organizations",
    "policy_rules",
    "users",
)

SUPABASE_CLIENT_ROLES = ("anon", "authenticated")


def _qualified_tables() -> str:
    return ", ".join(f'public."{table_name}"' for table_name in PUBLIC_TABLES)


def _set_client_privileges(role: str, *, grant: bool) -> None:
    action = "GRANT ALL PRIVILEGES ON TABLE" if grant else "REVOKE ALL PRIVILEGES ON TABLE"
    destination = f"TO {role}" if grant else f"FROM {role}"
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    {action} {_qualified_tables()} {destination};
                END IF;
            END
            $$;
            """
        )
    )


def _set_default_client_privileges(role: str, *, grant: bool) -> None:
    action = "GRANT ALL PRIVILEGES" if grant else "REVOKE ALL PRIVILEGES"
    destination = f"TO {role}" if grant else f"FROM {role}"
    statements = "\n".join(
        "                    "
        f"EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public {action} "
        f"ON {object_type} {destination}';"
        for object_type in ("TABLES", "SEQUENCES", "FUNCTIONS")
    )
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
{statements}
                END IF;
            END
            $$;
            """
        )
    )


def upgrade() -> None:
    for table_name in PUBLIC_TABLES:
        op.execute(sa.text(f'ALTER TABLE public."{table_name}" ENABLE ROW LEVEL SECURITY'))

    for role in SUPABASE_CLIENT_ROLES:
        _set_client_privileges(role, grant=False)
        _set_default_client_privileges(role, grant=False)


def downgrade() -> None:
    for role in SUPABASE_CLIENT_ROLES:
        _set_default_client_privileges(role, grant=True)
        _set_client_privileges(role, grant=True)

    for table_name in PUBLIC_TABLES:
        op.execute(sa.text(f'ALTER TABLE public."{table_name}" DISABLE ROW LEVEL SECURITY'))
