"""Single-use approvals on PostgreSQL: atomic claims, tenant scope and the fail-closed migration."""

import os
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.core.approval_risk import covering_risk_levels
from app.core.config import get_settings
from app.core.tenancy import set_current_organization_id
from app.models.agent import Agent, AgentRiskLevel
from app.models.approval import Approval, ApprovalStatus
from app.models.organization import Organization
from app.repositories import approvals as approval_repository

ADMIN_URL = os.environ.get("AGENTHQ_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL, reason="set AGENTHQ_TEST_POSTGRES_URL to a disposable PostgreSQL server"
)
BACKEND = Path(__file__).parents[1]
BEFORE = "202611170001"


def admin_engine() -> Engine:
    assert ADMIN_URL is not None
    return create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")


def database_url(name: str) -> str:
    assert ADMIN_URL is not None
    return make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)


def alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def migrate(name: str, revision: str) -> None:
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url(name)
    get_settings.cache_clear()
    try:
        command.upgrade(alembic_config(), revision)
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


@pytest.fixture()
def database() -> Iterator[str]:
    name = f"agenthq_single_use_{uuid4().hex[:8]}"
    engine = admin_engine()
    with engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield name
    finally:
        with engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        engine.dispose()


def seed(db: Session, *, status: ApprovalStatus = ApprovalStatus.APPROVED) -> tuple[UUID, UUID]:
    organization = Organization(name=f"Org {uuid4().hex[:6]}", slug=f"org-{uuid4().hex[:8]}")
    db.add(organization)
    db.flush()
    agent = Agent(
        organization_id=organization.id,
        name="Payments Agent",
        owner="owner@example.com",
        department="Finance",
        risk_level=AgentRiskLevel.HIGH,
    )
    db.add(agent)
    db.flush()
    approval = Approval(
        organization_id=organization.id,
        agent_id=agent.id,
        requested_action="transfer_funds",
        risk_level=AgentRiskLevel.HIGH,
        status=status,
    )
    db.add(approval)
    db.commit()
    return organization.id, approval.id


def claim(session: sessionmaker[Session], organization_id: UUID, approval_id: UUID) -> bool:
    with session() as db:
        set_current_organization_id(db, organization_id)
        approval = db.get(Approval, approval_id)
        assert approval is not None
        claimed = approval_repository.claim_approval_pending(
            db,
            approval_id,
            agent_id=approval.agent_id,
            requested_action="transfer_funds",
            allowed_risk_levels=covering_risk_levels(AgentRiskLevel.HIGH),
            execution_id=uuid4(),
            consumed_at=datetime.now(UTC),
        )
        db.commit()
        return claimed


def test_concurrent_claims_succeed_exactly_once(database: str) -> None:
    migrate(database, "head")
    engine = create_engine(database_url(database), pool_size=10, max_overflow=0)
    session = sessionmaker(bind=engine, autoflush=False)
    try:
        with session() as db:
            organization_id, approval_id = seed(db)
        attempts = 8
        barrier = threading.Barrier(attempts)
        results: list[bool] = []
        lock = threading.Lock()

        def attempt() -> None:
            barrier.wait()
            outcome = claim(session, organization_id, approval_id)
            with lock:
                results.append(outcome)

        threads = [threading.Thread(target=attempt) for _ in range(attempts)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert sorted(results) == [False] * (attempts - 1) + [True]
        with session() as db:
            stored = db.get(Approval, approval_id)
            assert stored is not None
            assert stored.consumed_at is not None
            assert stored.consumed_by_execution_id is not None
    finally:
        engine.dispose()


def test_claim_is_scoped_to_the_approval_organization(database: str) -> None:
    migrate(database, "head")
    engine = create_engine(database_url(database))
    session = sessionmaker(bind=engine, autoflush=False)
    try:
        with session() as db:
            organization_a, approval_a = seed(db)
            organization_b, _ = seed(db)

        assert claim(session, organization_b, approval_a) is False
        assert claim(session, organization_a, approval_a) is True
    finally:
        engine.dispose()


def test_migration_fails_closed_for_existing_approved_records(database: str) -> None:
    migrate(database, BEFORE)
    engine = create_engine(database_url(database))
    try:
        organization_id, agent_id = uuid4(), uuid4()
        approvals = {status: uuid4() for status in ("approved", "pending", "rejected")}
        used = uuid4()
        execution_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO organizations (id, name, slug, created_at, updated_at) "
                    "VALUES (:id, 'Legacy Org', 'legacy-org', now(), now())"
                ),
                {"id": organization_id},
            )
            connection.execute(
                text(
                    "INSERT INTO agents (id, organization_id, name, owner, department, "
                    "risk_level, status, created_at, updated_at) VALUES (:id, :org, 'Legacy', "
                    "'owner@example.com', 'Finance', 'high', 'active', now(), now())"
                ),
                {"id": agent_id, "org": organization_id},
            )
            for status, approval_id in [*approvals.items(), ("approved", used)]:
                connection.execute(
                    text(
                        "INSERT INTO approvals (id, organization_id, agent_id, requested_action, "
                        "requested_by, status, risk_level, requested_at) VALUES (:id, :org, "
                        ":agent, 'transfer_funds', 'system', :status, 'high', now())"
                    ),
                    {
                        "id": approval_id,
                        "org": organization_id,
                        "agent": agent_id,
                        "status": status,
                    },
                )
            connection.execute(
                text(
                    "INSERT INTO executions (id, organization_id, agent_id, action_name, status, "
                    "risk_level, approval_id, started_at, created_at) VALUES (:id, :org, :agent, "
                    "'transfer_funds', 'succeeded', 'high', :approval, now(), now())"
                ),
                {"id": execution_id, "org": organization_id, "agent": agent_id, "approval": used},
            )

        migrate(database, "head")

        with engine.connect() as connection:
            rows = {
                row.id: row
                for row in connection.execute(
                    text("SELECT id, status, consumed_at, consumed_by_execution_id FROM approvals")
                )
            }
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert revision == "202611220001"
        assert rows[approvals["approved"]].consumed_at is not None  # unknown history: closed
        assert rows[approvals["approved"]].consumed_by_execution_id is None
        assert rows[used].consumed_at is not None
        assert rows[used].consumed_by_execution_id == execution_id
        for status in ("pending", "rejected"):
            assert rows[approvals[status]].consumed_at is None
            assert rows[approvals[status]].status == status
    finally:
        engine.dispose()
