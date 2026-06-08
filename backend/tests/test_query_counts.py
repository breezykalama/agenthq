from collections.abc import Callable, Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.tenancy import set_current_organization_id
from app.db.base import Base
from app.models.agent import Agent, AgentRiskLevel, AgentStatus
from app.models.organization import Organization
from app.services import compliance as compliance_service
from app.services import dashboard as dashboard_service


@contextmanager
def count_queries(engine: Engine) -> Iterator[list[str]]:
    statements: list[str] = []

    def record_query(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_query)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record_query)


@contextmanager
def query_count_session() -> Iterator[tuple[Session, Engine, UUID]]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        organization = Organization(name="Query Count Org", slug="query-count-org")
        db.add(organization)
        db.flush()
        set_current_organization_id(db, organization.id)
        agent = Agent(
            organization_id=organization.id,
            name="Query Count Agent",
            owner="platform-team",
            department="governance",
            risk_level=AgentRiskLevel.LOW,
            status=AgentStatus.ACTIVE,
        )
        db.add(agent)
        db.commit()
        db.refresh(agent)
        yield db, engine, agent.id
    engine.dispose()


def assert_query_count(
    operation: Callable[[], object],
    engine: Engine,
    *,
    maximum: int,
) -> None:
    with count_queries(engine) as statements:
        operation()
    assert len(statements) <= maximum, statements


def test_dashboard_summary_query_count() -> None:
    with query_count_session() as (db, engine, _agent_id):
        assert_query_count(lambda: dashboard_service.get_summary(db), engine, maximum=6)


def test_grouped_dashboard_endpoint_query_counts() -> None:
    with query_count_session() as (db, engine, _agent_id):
        operations = [
            lambda: dashboard_service.get_agents_by_risk(db),
            lambda: dashboard_service.get_executions_by_status(db),
            lambda: dashboard_service.get_approvals_by_status(db),
        ]
        for operation in operations:
            assert_query_count(operation, engine, maximum=1)


def test_compliance_summary_query_count() -> None:
    with query_count_session() as (db, engine, _agent_id):
        assert_query_count(lambda: compliance_service.get_summary(db), engine, maximum=5)


def test_agent_compliance_report_query_count() -> None:
    with query_count_session() as (db, engine, agent_id):
        assert_query_count(
            lambda: compliance_service.get_agent_report(db, agent_id),
            engine,
            maximum=2,
        )
