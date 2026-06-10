from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "202606100001_enable_rls_for_public_tables.py"
)

PUBLIC_TABLES = {
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
}


def test_rls_migration_protects_every_public_table_without_forcing_rls() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")

    for table_name in PUBLIC_TABLES:
        assert f'"{table_name}"' in migration

    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "REVOKE ALL PRIVILEGES ON TABLE" in migration
    assert "ALTER DEFAULT PRIVILEGES IN SCHEMA public" in migration
    assert "FORCE ROW LEVEL SECURITY" not in migration
    assert "CREATE POLICY" not in migration


def test_rls_migration_has_explicit_rollback() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")

    assert "DISABLE ROW LEVEL SECURITY" in migration
    assert "GRANT ALL PRIVILEGES ON TABLE" in migration
