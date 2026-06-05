from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.agent_tool import (
    AgentToolCreate,
    AgentToolListResponse,
    AgentToolRead,
    AgentToolUpdate,
)
from app.services import agent_tools as agent_tool_service

router = APIRouter(prefix="/api/v1/agents/{agent_id}/tools", tags=["agent-tools"])
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=AgentToolRead, status_code=status.HTTP_201_CREATED)
def create_agent_tool(
    agent_id: UUID,
    agent_tool_create: AgentToolCreate,
    db: DatabaseSession,
) -> AgentToolRead:
    try:
        return AgentToolRead.model_validate(
            agent_tool_service.create_agent_tool(db, agent_id, agent_tool_create)
        )
    except agent_tool_service.AgentToolAgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found.",
        ) from exc
    except agent_tool_service.DuplicateAgentToolNameError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An enabled or disabled tool with this name already exists for this agent.",
        ) from exc


@router.get("", response_model=AgentToolListResponse)
def list_agent_tools(agent_id: UUID, db: DatabaseSession) -> AgentToolListResponse:
    try:
        agent_tools, total = agent_tool_service.list_agent_tools(db, agent_id)
    except agent_tool_service.AgentToolAgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found.",
        ) from exc

    return AgentToolListResponse(
        items=[AgentToolRead.model_validate(agent_tool) for agent_tool in agent_tools],
        total=total,
    )


@router.get("/{tool_id}", response_model=AgentToolRead)
def get_agent_tool(agent_id: UUID, tool_id: UUID, db: DatabaseSession) -> AgentToolRead:
    try:
        return AgentToolRead.model_validate(
            agent_tool_service.get_agent_tool_by_id(db, agent_id, tool_id)
        )
    except agent_tool_service.AgentToolAgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found.",
        ) from exc
    except agent_tool_service.AgentToolNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tool not found.",
        ) from exc


@router.patch("/{tool_id}", response_model=AgentToolRead)
def update_agent_tool(
    agent_id: UUID,
    tool_id: UUID,
    agent_tool_update: AgentToolUpdate,
    db: DatabaseSession,
) -> AgentToolRead:
    try:
        return AgentToolRead.model_validate(
            agent_tool_service.update_agent_tool(db, agent_id, tool_id, agent_tool_update)
        )
    except agent_tool_service.AgentToolAgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found.",
        ) from exc
    except agent_tool_service.AgentToolNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tool not found.",
        ) from exc
    except agent_tool_service.DuplicateAgentToolNameError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An enabled or disabled tool with this name already exists for this agent.",
        ) from exc


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent_tool(agent_id: UUID, tool_id: UUID, db: DatabaseSession) -> None:
    try:
        agent_tool_service.soft_delete_agent_tool(db, agent_id, tool_id)
    except agent_tool_service.AgentToolAgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found.",
        ) from exc
    except agent_tool_service.AgentToolNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tool not found.",
        ) from exc
