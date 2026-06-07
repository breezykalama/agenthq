from uuid import UUID

from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.audit_log import AuditAction, JsonObject
from app.repositories import agents as agent_repository
from app.schemas.agent import AgentCreate, AgentRead, AgentUpdate
from app.schemas.audit_log import AuditLogCreate
from app.services import audit_logs as audit_log_service


class AgentNotFoundError(Exception):
    pass


class DuplicateAgentNameError(Exception):
    pass


def serialize_agent(agent: Agent) -> JsonObject:
    return AgentRead.model_validate(agent).model_dump(mode="json")


def create_agent(db: Session, agent_create: AgentCreate) -> Agent:
    if agent_repository.get_agent_by_name(db, agent_create.name) is not None:
        raise DuplicateAgentNameError

    agent = agent_repository.create_agent(db, agent_create)
    audit_log_service.create_audit_log(
        db,
        AuditLogCreate(
            action=AuditAction.AGENT_CREATED,
            entity_type="agent",
            entity_id=agent.id,
            before=None,
            after=serialize_agent(agent),
        ),
    )
    return agent


def list_agents(db: Session, owner: str | None = None) -> tuple[list[Agent], int]:
    return agent_repository.list_agents(db, owner=owner)


def get_agent_by_id(db: Session, agent_id: UUID) -> Agent:
    agent = agent_repository.get_agent_by_id(db, agent_id)
    if agent is None:
        raise AgentNotFoundError
    return agent


def update_agent(db: Session, agent_id: UUID, agent_update: AgentUpdate) -> Agent:
    agent = get_agent_by_id(db, agent_id)
    before = serialize_agent(agent)
    update_values = agent_update.model_dump(exclude_unset=True)

    updated_name = update_values.get("name")
    if isinstance(updated_name, str) and updated_name != agent.name:
        existing_agent = agent_repository.get_agent_by_name(db, updated_name)
        if existing_agent is not None and existing_agent.id != agent.id:
            raise DuplicateAgentNameError

    updated_agent = agent_repository.update_agent(db, agent, update_values)
    audit_log_service.create_audit_log(
        db,
        AuditLogCreate(
            action=AuditAction.AGENT_UPDATED,
            entity_type="agent",
            entity_id=updated_agent.id,
            before=before,
            after=serialize_agent(updated_agent),
        ),
    )
    return updated_agent


def soft_delete_agent(db: Session, agent_id: UUID) -> None:
    agent = get_agent_by_id(db, agent_id)
    before = serialize_agent(agent)
    deleted_agent = agent_repository.soft_delete_agent(db, agent)
    audit_log_service.create_audit_log(
        db,
        AuditLogCreate(
            action=AuditAction.AGENT_DELETED,
            entity_type="agent",
            entity_id=deleted_agent.id,
            before=before,
            after=serialize_agent(deleted_agent),
        ),
    )
