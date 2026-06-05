from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.repositories import agents as agent_repository
from app.seed import seed_demo_data


def test_seed_demo_data_runs_without_crashing() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    with testing_session_local() as db:
        seed_demo_data(db)
        policy_agent = agent_repository.get_agent_by_name(db, "Policy Knowledge Agent")

    assert policy_agent is not None
