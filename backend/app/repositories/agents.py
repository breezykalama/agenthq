from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.schemas.agent import AgentCreate


def create_agent(db: Session, agent_create: AgentCreate) -> Agent:
    agent = Agent(**agent_create.model_dump())
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


def list_agents(db: Session) -> tuple[list[Agent], int]:
    statement = select(Agent).where(Agent.deleted_at.is_(None)).order_by(Agent.created_at.desc())
    count_statement = select(func.count()).select_from(Agent).where(Agent.deleted_at.is_(None))

    agents = list(db.scalars(statement).all())
    total = db.scalar(count_statement) or 0
    return agents, total


def get_agent_by_id(db: Session, agent_id: UUID) -> Agent | None:
    statement = select(Agent).where(Agent.id == agent_id, Agent.deleted_at.is_(None))
    return db.scalar(statement)


def get_agent_by_name(db: Session, name: str) -> Agent | None:
    statement = select(Agent).where(Agent.name == name, Agent.deleted_at.is_(None))
    return db.scalar(statement)


def update_agent(db: Session, agent: Agent, values: dict[str, object]) -> Agent:
    for field, value in values.items():
        setattr(agent, field, value)

    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


def soft_delete_agent(db: Session, agent: Agent) -> Agent:
    agent.deleted_at = datetime.now(UTC)
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent
