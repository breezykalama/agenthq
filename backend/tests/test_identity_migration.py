from pathlib import Path

VERSIONS = Path(__file__).parents[1] / "alembic" / "versions"
HARDENING_PATH = VERSIONS / "202611170001_harden_identity_flows.py"
MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "202606270001_add_email_identity_flows.py"
)


def test_identity_migration_adds_tokens_indexes_and_rls() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")

    assert '"email_verified"' in migration
    assert '"email_verified_at"' in migration
    assert '"email_verification_tokens"' in migration
    assert '"password_reset_tokens"' in migration
    assert "ix_email_verification_tokens_user_id" in migration
    assert "ix_password_reset_tokens_user_id" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "REVOKE ALL PRIVILEGES ON TABLE" in migration


def test_identity_migration_has_explicit_downgrade() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")

    assert 'op.drop_table("password_reset_tokens")' in migration
    assert 'op.drop_table("email_verification_tokens")' in migration
    assert 'op.drop_column("users", "email_verified")' in migration


def test_hardening_migration_chain_and_grandfathering() -> None:
    migration = HARDENING_PATH.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "202606270001"' in migration
    assert '"email_verification_required"' in migration
    assert "server_default=sa.false()" in migration
    assert '"auth_version", sa.Integer(), server_default="0", nullable=False' in migration


def test_hardening_migration_outbox_has_no_raw_token_column_and_rls() -> None:
    migration = HARDENING_PATH.read_text(encoding="utf-8")

    assert '"email_outbox"' in migration
    assert '"token_nonce"' in migration
    assert '"raw_token"' not in migration
    assert "uq_email_outbox_kind_token" in migration
    assert 'ALTER TABLE public."email_outbox" ENABLE ROW LEVEL SECURITY' in migration
    assert "REVOKE ALL PRIVILEGES" in migration
    assert 'op.drop_table("email_outbox")' in migration


def test_model_audit_actions_are_all_added_by_migrations() -> None:
    from app.models.audit_log import AuditAction

    sources = "\n".join(path.read_text(encoding="utf-8") for path in VERSIONS.glob("*.py"))
    missing = [
        action.value
        for action in AuditAction
        if f"'{action.value}'" not in sources and f'"{action.value}"' not in sources
    ]
    assert missing == []
