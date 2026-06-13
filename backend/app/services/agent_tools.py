from uuid import UUID

from sqlalchemy.orm import Session

from app.core.security import assert_resource_in_org, log_resource_access_denied
from app.models.agent_tool import AgentTool
from app.models.audit_log import AuditAction, JsonObject
from app.repositories import agent_tools as agent_tool_repository
from app.repositories import agents as agent_repository
from app.repositories import tool_governance as governance_repository
from app.schemas.agent_tool import AgentToolCreate, AgentToolRead, AgentToolUpdate
from app.schemas.audit_log import AuditLogCreate
from app.services import audit_logs as audit_log_service
from app.services import governance_alerts as alert_service
from app.services import tool_governance as tool_governance_service


class AgentToolNotFoundError(Exception):
    pass


class AgentToolAgentNotFoundError(Exception):
    pass


class DuplicateAgentToolNameError(Exception):
    pass


def serialize_agent_tool(agent_tool: AgentTool) -> JsonObject:
    return AgentToolRead.model_validate(agent_tool).model_dump(mode="json")


def ensure_agent_exists(db: Session, agent_id: UUID) -> None:
    if agent_repository.get_agent_by_id(db, agent_id) is None:
        log_resource_access_denied(
            db,
            attempted_action="access_agent_tools",
            target_resource=f"agent:{agent_id}",
        )
        raise AgentToolAgentNotFoundError


def create_agent_tool(
    db: Session,
    agent_id: UUID,
    agent_tool_create: AgentToolCreate,
) -> AgentTool:
    ensure_agent_exists(db, agent_id)
    existing_tool = agent_tool_repository.get_agent_tool_by_name(
        db,
        agent_id,
        agent_tool_create.name,
    )
    if existing_tool is not None:
        raise DuplicateAgentToolNameError

    agent_tool = agent_tool_repository.create_agent_tool(db, agent_id, agent_tool_create)
    audit_log_service.create_audit_log(
        db,
        AuditLogCreate(
            action=AuditAction.AGENT_TOOL_CREATED,
            entity_type="agent_tool",
            entity_id=agent_tool.id,
            before=None,
            after=serialize_agent_tool(agent_tool),
        ),
    )
    return agent_tool


def list_agent_tools(
    db: Session,
    agent_id: UUID,
    *,
    limit: int,
    offset: int,
) -> tuple[list[AgentTool], int]:
    ensure_agent_exists(db, agent_id)
    return agent_tool_repository.list_agent_tools(db, agent_id, limit=limit, offset=offset)


def get_agent_tool_by_id(db: Session, agent_id: UUID, tool_id: UUID) -> AgentTool:
    ensure_agent_exists(db, agent_id)
    agent_tool = agent_tool_repository.get_agent_tool_by_id(db, agent_id, tool_id)
    if agent_tool is None:
        log_resource_access_denied(
            db,
            attempted_action="access_agent_tool",
            target_resource=f"agent_tool:{tool_id}",
        )
        raise AgentToolNotFoundError
    assert_resource_in_org(db, agent_tool, resource_name="Tool")
    return agent_tool


def update_agent_tool(
    db: Session,
    agent_id: UUID,
    tool_id: UUID,
    agent_tool_update: AgentToolUpdate,
) -> AgentTool:
    agent_tool = get_agent_tool_by_id(db, agent_id, tool_id)
    before = serialize_agent_tool(agent_tool)
    update_values = agent_tool_update.model_dump(exclude_unset=True)

    updated_name = update_values.get("name")
    if isinstance(updated_name, str) and updated_name != agent_tool.name:
        existing_tool = agent_tool_repository.get_agent_tool_by_name(db, agent_id, updated_name)
        if existing_tool is not None and existing_tool.id != agent_tool.id:
            raise DuplicateAgentToolNameError

    updated_tool = agent_tool_repository.update_agent_tool(db, agent_tool, update_values)
    audit_log_service.create_audit_log(
        db,
        AuditLogCreate(
            action=AuditAction.AGENT_TOOL_UPDATED,
            entity_type="agent_tool",
            entity_id=updated_tool.id,
            before=before,
            after=serialize_agent_tool(updated_tool),
        ),
    )
    if updated_tool.discovered_from_mcp_server_id is not None:
        policies = governance_repository.list_enabled_policy_rules(db)
        alert_service.reconcile_tool_pending(
            db,
            updated_tool,
            has_policy=bool(tool_governance_service.applicable_policies(updated_tool, policies)),
        )
        from app.services import risk_compliance as risk_service

        risk_service.reconcile(db, commit=False)
        db.commit()
    return updated_tool


def soft_delete_agent_tool(db: Session, agent_id: UUID, tool_id: UUID) -> None:
    agent_tool = get_agent_tool_by_id(db, agent_id, tool_id)
    before = serialize_agent_tool(agent_tool)
    deleted_tool = agent_tool_repository.soft_delete_agent_tool(db, agent_tool)
    audit_log_service.create_audit_log(
        db,
        AuditLogCreate(
            action=AuditAction.AGENT_TOOL_DELETED,
            entity_type="agent_tool",
            entity_id=deleted_tool.id,
            before=before,
            after=serialize_agent_tool(deleted_tool),
        ),
    )
