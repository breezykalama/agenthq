from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.agent import AgentCreate, AgentListResponse, AgentRead, AgentUpdate
from app.services import agents as agent_service

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=AgentRead, status_code=status.HTTP_201_CREATED)
def create_agent(agent_create: AgentCreate, db: DatabaseSession) -> AgentRead:
    try:
        return AgentRead.model_validate(agent_service.create_agent(db, agent_create))
    except agent_service.DuplicateAgentNameError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An agent with this name already exists.",
        ) from exc


@router.get("", response_model=AgentListResponse)
def list_agents(db: DatabaseSession) -> AgentListResponse:
    agents, total = agent_service.list_agents(db)
    return AgentListResponse(
        items=[AgentRead.model_validate(agent) for agent in agents],
        total=total,
    )


@router.get("/{agent_id}", response_model=AgentRead)
def get_agent(agent_id: UUID, db: DatabaseSession) -> AgentRead:
    try:
        return AgentRead.model_validate(agent_service.get_agent_by_id(db, agent_id))
    except agent_service.AgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found.",
        ) from exc


@router.patch("/{agent_id}", response_model=AgentRead)
def update_agent(
    agent_id: UUID,
    agent_update: AgentUpdate,
    db: DatabaseSession,
) -> AgentRead:
    try:
        return AgentRead.model_validate(agent_service.update_agent(db, agent_id, agent_update))
    except agent_service.AgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found.",
        ) from exc
    except agent_service.DuplicateAgentNameError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An agent with this name already exists.",
        ) from exc


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent(agent_id: UUID, db: DatabaseSession) -> None:
    try:
        agent_service.soft_delete_agent(db, agent_id)
    except agent_service.AgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found.",
        ) from exc
