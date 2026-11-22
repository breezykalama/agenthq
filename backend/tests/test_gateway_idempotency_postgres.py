"""Gateway idempotency on PostgreSQL: concurrent requests dispatch at most once per key."""

import os
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.adapters.mcp_discovery import MCPDiscoveryTarget
from app.adapters.mcp_execution import MCPToolExecutionResult
from app.core.config import get_settings
from app.core.security import hash_password
from app.models.agent import Agent, AgentRiskLevel
from app.models.agent_tool import AgentTool, AgentToolPermission
from app.models.mcp_gateway import MCPGatewayCallRecord, MCPGatewayCallState, MCPGatewayToken
from app.models.mcp_server import MCPServer
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.schemas.mcp_gateway import MCPGatewayToolCall
from app.services import mcp_gateway as gateway_service

ADMIN_URL = os.environ.get("AGENTHQ_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL, reason="set AGENTHQ_TEST_POSTGRES_URL to a disposable PostgreSQL server"
)
BACKEND = Path(__file__).parents[1]
RAW_TOKEN = "agenthq-test-gateway-token-0123456789"


def admin_engine() -> Engine:
    assert ADMIN_URL is not None
    return create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")


def database_url(name: str) -> str:
    assert ADMIN_URL is not None
    return make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)


def alembic(name: str, action: str, revision: str) -> None:
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url(name)
    get_settings.cache_clear()
    try:
        config = Config()
        config.set_main_option("script_location", str(BACKEND / "alembic"))
        getattr(command, action)(config, revision)
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


@pytest.fixture()
def database() -> Iterator[str]:
    name = f"agenthq_idempotency_{uuid4().hex[:8]}"
    engine = admin_engine()
    with engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        alembic(name, "upgrade", "head")
        yield name
    finally:
        with engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        engine.dispose()


@dataclass(frozen=True)
class Gateway:
    session: sessionmaker[Session]
    server_id: UUID
    tool_id: UUID


@pytest.fixture()
def gateway(database: str) -> Iterator[Gateway]:
    engine = create_engine(database_url(database), pool_size=12, max_overflow=0)
    session = sessionmaker(bind=engine, autoflush=False)
    with session() as db:
        organization = Organization(name="Payments Org", slug="payments-org")
        db.add(organization)
        db.flush()
        user = User(
            email="admin@example.com",
            full_name="Admin",
            password_hash=hash_password("AdminPassword123!"),
            role=UserRole.ADMIN,
        )
        agent = Agent(
            organization_id=organization.id,
            name="Payments Agent",
            owner="admin@example.com",
            department="Finance",
            risk_level=AgentRiskLevel.MEDIUM,
        )
        db.add_all([user, agent])
        db.flush()
        server = MCPServer(
            organization_id=organization.id,
            agent_id=agent.id,
            name="Payments MCP",
            server_url="https://payments.example.com/mcp",
        )
        db.add(server)
        db.flush()
        tool = AgentTool(
            organization_id=organization.id,
            agent_id=agent.id,
            name="transfer_funds",
            discovered_from_mcp_server_id=server.id,
            reviewed_at=datetime.now(UTC),
            permission=AgentToolPermission.EXECUTE,
            risk_level=AgentRiskLevel.MEDIUM,
        )
        db.add(tool)
        db.flush()
        db.add(
            MCPGatewayToken(
                organization_id=organization.id,
                agent_id=agent.id,
                mcp_server_id=server.id,
                allowed_mcp_server_ids=[str(server.id)],
                name="Payments client",
                token_hash=gateway_service.hash_gateway_token(RAW_TOKEN),
                created_by_user_id=user.id,
            )
        )
        db.commit()
        result = Gateway(session=session, server_id=server.id, tool_id=tool.id)
    try:
        yield result
    finally:
        engine.dispose()


class SlowUpstream:
    """Holds every call open long enough for concurrent duplicates to overlap with it."""

    def __init__(self) -> None:
        self.calls = 0
        self.lock = threading.Lock()

    def call_tool(
        self,
        target: MCPDiscoveryTarget,
        tool_name: str,
        arguments: dict[str, object],
    ) -> MCPToolExecutionResult:
        with self.lock:
            self.calls += 1
        time.sleep(0.5)
        return MCPToolExecutionResult(payload={"content": [{"type": "text", "text": "done"}]})


def gateway_call(gateway: Gateway, upstream: SlowUpstream, key: str) -> object:
    with gateway.session() as db:
        token = gateway_service.authenticate_token(db, RAW_TOKEN, gateway.server_id)
        try:
            return gateway_service.call_gateway_tool(
                db,
                token,
                gateway.tool_id,
                MCPGatewayToolCall(
                    input_payload={"account": "1", "amount": 10},
                    idempotency_key=key,
                ),
                upstream,
                server_id=gateway.server_id,
            )
        except Exception as exc:  # recorded and asserted on below
            return exc


def test_concurrent_requests_with_one_key_dispatch_exactly_once(gateway: Gateway) -> None:
    upstream = SlowUpstream()
    attempts = 8
    barrier = threading.Barrier(attempts)
    outcomes: list[object] = []
    lock = threading.Lock()

    def attempt() -> None:
        barrier.wait()
        outcome = gateway_call(gateway, upstream, "payment-42")
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=attempt) for _ in range(attempts)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert upstream.calls == 1
    assert len(outcomes) == attempts
    dispatched = [
        outcome
        for outcome in outcomes
        if not isinstance(outcome, Exception) and not getattr(outcome, "idempotent_replay", False)
    ]
    conflicts = [
        outcome
        for outcome in outcomes
        if isinstance(outcome, gateway_service.MCPGatewayIdempotencyConflictError)
    ]
    replays = [outcome for outcome in outcomes if getattr(outcome, "idempotent_replay", False)]
    unexpected = [
        outcome
        for outcome in outcomes
        if isinstance(outcome, Exception)
        and not isinstance(outcome, gateway_service.MCPGatewayIdempotencyConflictError)
    ]
    assert unexpected == []  # no unhandled database errors
    assert len(dispatched) == 1
    assert len(conflicts) + len(replays) == attempts - 1
    with gateway.session() as db:
        records = db.query(MCPGatewayCallRecord).all()
        assert len(records) == 1
        assert records[0].state == MCPGatewayCallState.COMPLETED
        assert records[0].request_hash is not None
    # Once completed, the same key replays without dispatching again.
    replay = gateway_call(gateway, upstream, "payment-42")
    assert getattr(replay, "idempotent_replay", False) is True
    assert upstream.calls == 1


def test_migration_keeps_existing_records_replayable(database: str, gateway: Gateway) -> None:
    upstream = SlowUpstream()
    first = gateway_call(gateway, upstream, "legacy-key")
    assert not isinstance(first, Exception)
    # Rebuild the columns this revision adds, as if the record had been written before it.
    alembic(database, "downgrade", "202611220001")
    alembic(database, "upgrade", "head")

    with gateway.session() as db:
        record = db.query(MCPGatewayCallRecord).one()
        assert record.state == MCPGatewayCallState.COMPLETED
        assert record.request_hash is None
        assert record.execution_id is not None
        assert record.response_payload is not None
    replay = gateway_call(gateway, upstream, "legacy-key")

    assert getattr(replay, "idempotent_replay", False) is True
    assert upstream.calls == 1
