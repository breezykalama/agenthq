from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.tenancy import get_current_organization_id
from app.models.agent_tool import AgentTool
from app.schemas.agent_tool import AgentToolCreate


def create_agent_tool(
    db: Session,
    agent_id: UUID,
    agent_tool_create: AgentToolCreate,
) -> AgentTool:
    agent_tool = AgentTool(
        organization_id=get_current_organization_id(db),
        agent_id=agent_id,
        **agent_tool_create.model_dump(),
    )
    db.add(agent_tool)
    db.commit()
    db.refresh(agent_tool)
    return agent_tool


def create_agent_tool_pending(
    db: Session,
    agent_id: UUID,
    agent_tool_create: AgentToolCreate,
) -> AgentTool:
    agent_tool = AgentTool(
        organization_id=get_current_organization_id(db),
        agent_id=agent_id,
        **agent_tool_create.model_dump(),
    )
    db.add(agent_tool)
    db.flush()
    return agent_tool


def list_agent_tools(
    db: Session,
    agent_id: UUID,
    *,
    limit: int,
    offset: int,
) -> tuple[list[AgentTool], int]:
    statement = (
        select(AgentTool)
        .where(
            AgentTool.organization_id == get_current_organization_id(db),
            AgentTool.agent_id == agent_id,
            AgentTool.deleted_at.is_(None),
        )
        .order_by(AgentTool.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    count_statement = (
        select(func.count())
        .select_from(AgentTool)
        .where(
            AgentTool.organization_id == get_current_organization_id(db),
            AgentTool.agent_id == agent_id,
            AgentTool.deleted_at.is_(None),
        )
    )

    agent_tools = list(db.scalars(statement).all())
    total = db.scalar(count_statement) or 0
    return agent_tools, total


def get_agent_tool_by_id(db: Session, agent_id: UUID, tool_id: UUID) -> AgentTool | None:
    statement = select(AgentTool).where(
        AgentTool.organization_id == get_current_organization_id(db),
        AgentTool.agent_id == agent_id,
        AgentTool.id == tool_id,
        AgentTool.deleted_at.is_(None),
    )
    return db.scalar(statement)


def get_agent_tool_by_name(db: Session, agent_id: UUID, name: str) -> AgentTool | None:
    statement = select(AgentTool).where(
        AgentTool.organization_id == get_current_organization_id(db),
        AgentTool.agent_id == agent_id,
        AgentTool.name == name,
        AgentTool.deleted_at.is_(None),
    )
    return db.scalar(statement)


def update_agent_tool(db: Session, agent_tool: AgentTool, values: dict[str, object]) -> AgentTool:
    for field, value in values.items():
        setattr(agent_tool, field, value)

    db.add(agent_tool)
    db.commit()
    db.refresh(agent_tool)
    return agent_tool


def update_agent_tool_pending(
    db: Session,
    agent_tool: AgentTool,
    values: dict[str, object],
) -> AgentTool:
    for field, value in values.items():
        setattr(agent_tool, field, value)
    db.add(agent_tool)
    db.flush()
    return agent_tool


def soft_delete_agent_tool(db: Session, agent_tool: AgentTool) -> AgentTool:
    agent_tool.deleted_at = datetime.now(UTC)
    db.add(agent_tool)
    db.commit()
    db.refresh(agent_tool)
    return agent_tool
