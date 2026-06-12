from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.adapters.mcp_discovery import MCPDiscoveryAdapter, MCPDiscoveryTarget
from app.core.security import assert_resource_in_org, log_resource_access_denied
from app.models.agent import AgentRiskLevel, AgentStatus
from app.models.agent_tool import AgentToolPermission
from app.models.audit_log import AuditAction, AuditOutcome, JsonObject
from app.models.mcp_server import MCPAuthType, MCPServer, MCPServerStatus
from app.repositories import agent_tools as agent_tool_repository
from app.repositories import agents as agent_repository
from app.repositories import mcp_servers as mcp_server_repository
from app.schemas.agent import AgentCreate
from app.schemas.agent_tool import AgentToolCreate
from app.schemas.audit_log import AuditLogCreate
from app.schemas.mcp_server import (
    MCPServerCreate,
    MCPServerRead,
    MCPServerSyncResponse,
    MCPServerUpdate,
    validate_auth_configuration,
)
from app.services import agents as agent_service
from app.services import audit_logs as audit_log_service


class MCPServerNotFoundError(Exception):
    pass


class DuplicateMCPServerNameError(Exception):
    pass


class MCPServerSyncError(Exception):
    pass


class InvalidMCPServerAgentError(Exception):
    pass


class InvalidMCPServerConfigurationError(Exception):
    pass


MCP_DISCOVERY_FAILURE_MESSAGE = (
    "MCP discovery failed. Check server connectivity and configuration."
)


def serialize_mcp_server(mcp_server: MCPServer) -> JsonObject:
    return MCPServerRead.model_validate(mcp_server).model_dump(mode="json")


def create_mcp_server(db: Session, mcp_server_create: MCPServerCreate) -> MCPServer:
    validate_linked_agent(db, mcp_server_create.agent_id)
    validate_unique_name(db, mcp_server_create.name)
    mcp_server = mcp_server_repository.create_mcp_server(db, mcp_server_create)
    audit_log_service.create_audit_log(
        db,
        AuditLogCreate(
            action=AuditAction.MCP_SERVER_CREATED,
            entity_type="mcp_server",
            entity_id=mcp_server.id,
            before=None,
            after=serialize_mcp_server(mcp_server),
        ),
    )
    return mcp_server


def list_mcp_servers(db: Session, *, limit: int, offset: int) -> tuple[list[MCPServer], int]:
    return mcp_server_repository.list_mcp_servers(db, limit=limit, offset=offset)


def get_mcp_server_by_id(db: Session, mcp_server_id: UUID) -> MCPServer:
    mcp_server = mcp_server_repository.get_mcp_server_by_id(db, mcp_server_id)
    if mcp_server is None:
        log_resource_access_denied(
            db,
            attempted_action="access_mcp_server",
            target_resource=f"mcp_server:{mcp_server_id}",
        )
        raise MCPServerNotFoundError
    assert_resource_in_org(db, mcp_server, resource_name="MCP server")
    return mcp_server


def update_mcp_server(
    db: Session,
    mcp_server_id: UUID,
    mcp_server_update: MCPServerUpdate,
) -> MCPServer:
    mcp_server = get_mcp_server_by_id(db, mcp_server_id)
    before = serialize_mcp_server(mcp_server)
    update_values = mcp_server_update.model_dump(exclude_unset=True)
    if "agent_id" in update_values:
        agent_id = update_values["agent_id"]
        validate_linked_agent(db, agent_id if isinstance(agent_id, UUID) else None)
    updated_name = update_values.get("name")
    if isinstance(updated_name, str) and updated_name != mcp_server.name:
        validate_unique_name(db, updated_name)
    updated_auth_type = update_values.get("auth_type", mcp_server.auth_type)
    updated_secret_ref = update_values.get("auth_secret_ref", mcp_server.auth_secret_ref)
    try:
        if not isinstance(updated_auth_type, MCPAuthType):
            raise ValueError("Invalid MCP auth type.")
        if updated_secret_ref is not None and not isinstance(updated_secret_ref, str):
            raise ValueError("Invalid MCP auth secret reference.")
        validate_auth_configuration(updated_auth_type, updated_secret_ref)
    except ValueError as exc:
        raise InvalidMCPServerConfigurationError from exc

    updated_server = mcp_server_repository.update_mcp_server(db, mcp_server, update_values)
    audit_log_service.create_audit_log(
        db,
        AuditLogCreate(
            action=AuditAction.MCP_SERVER_UPDATED,
            entity_type="mcp_server",
            entity_id=updated_server.id,
            before=before,
            after=serialize_mcp_server(updated_server),
        ),
    )
    return updated_server


def soft_delete_mcp_server(db: Session, mcp_server_id: UUID) -> None:
    mcp_server = get_mcp_server_by_id(db, mcp_server_id)
    before = serialize_mcp_server(mcp_server)
    deleted_server = mcp_server_repository.soft_delete_mcp_server(db, mcp_server)
    audit_log_service.create_audit_log(
        db,
        AuditLogCreate(
            action=AuditAction.MCP_SERVER_DELETED,
            entity_type="mcp_server",
            entity_id=deleted_server.id,
            before=before,
            after=serialize_mcp_server(deleted_server),
        ),
    )


def sync_mcp_server(
    db: Session,
    mcp_server_id: UUID,
    adapter: MCPDiscoveryAdapter,
) -> MCPServerSyncResponse:
    mcp_server = get_mcp_server_by_id(db, mcp_server_id)
    before = serialize_mcp_server(mcp_server)

    try:
        discovered_tools = adapter.discover_tools(
            MCPDiscoveryTarget(
                server_url=mcp_server.server_url,
                transport_type=mcp_server.transport_type,
                auth_type=mcp_server.auth_type,
                auth_secret_ref=mcp_server.auth_secret_ref,
                request_timeout_seconds=mcp_server.request_timeout_seconds,
                connect_timeout_seconds=mcp_server.connect_timeout_seconds,
            )
        )
    except Exception as exc:
        record_sync_failure(db, mcp_server, before)
        raise MCPServerSyncError from exc

    try:
        agent_id = ensure_linked_agent(db, mcp_server)
        created_tools_count = 0
        updated_tools_count = 0
        for discovered_tool in discovered_tools:
            existing_tool = agent_tool_repository.get_agent_tool_by_name(
                db,
                agent_id,
                discovered_tool.name,
            )
            if existing_tool is None:
                agent_tool_repository.create_agent_tool_pending(
                    db,
                    agent_id,
                    AgentToolCreate(
                        name=discovered_tool.name,
                        description=discovered_tool.description,
                        permission=AgentToolPermission.EXECUTE,
                        risk_level=AgentRiskLevel.MEDIUM,
                        is_enabled=True,
                    ),
                )
                created_tools_count += 1
                continue

            agent_tool_repository.update_agent_tool_pending(
                db,
                existing_tool,
                {"description": discovered_tool.description},
            )
            updated_tools_count += 1

        synced_at = datetime.now(UTC)
        synced_server = mcp_server_repository.update_mcp_server_state_pending(
            db,
            mcp_server,
            {
                "agent_id": agent_id,
                "status": MCPServerStatus.CONNECTED,
                "last_sync_at": synced_at,
                "last_error": None,
            },
        )
        audit_log_service.create_critical_audit_log(
            db,
            AuditLogCreate(
                action=AuditAction.MCP_SERVER_SYNCED,
                entity_type="mcp_server",
                entity_id=synced_server.id,
                before=before,
                after=serialize_mcp_server(synced_server),
            ),
        )
        db.commit()
        db.refresh(synced_server)
    except audit_log_service.AuditLoggingError:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        record_sync_failure(db, mcp_server, before)
        raise MCPServerSyncError from exc
    return MCPServerSyncResponse(
        server_id=synced_server.id,
        agent_id=agent_id,
        discovered_tools_count=len(discovered_tools),
        created_tools_count=created_tools_count,
        updated_tools_count=updated_tools_count,
        status=synced_server.status,
        last_sync_at=synced_at,
    )


def record_sync_failure(db: Session, mcp_server: MCPServer, before: JsonObject) -> None:
    try:
        failed_server = mcp_server_repository.update_mcp_server_state_pending(
            db,
            mcp_server,
            {
                "status": MCPServerStatus.ERROR,
                "last_error": MCP_DISCOVERY_FAILURE_MESSAGE,
            },
        )
        audit_log_service.create_critical_audit_log(
            db,
            AuditLogCreate(
                action=AuditAction.MCP_SERVER_SYNC_FAILED,
                entity_type="mcp_server",
                entity_id=failed_server.id,
                before=before,
                after=serialize_mcp_server(failed_server),
                outcome=AuditOutcome.FAILED,
                reason=MCP_DISCOVERY_FAILURE_MESSAGE,
            ),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


def ensure_linked_agent(db: Session, mcp_server: MCPServer) -> UUID:
    if mcp_server.agent_id is not None:
        linked_agent = agent_repository.get_agent_by_id(db, mcp_server.agent_id)
        if linked_agent is None:
            raise InvalidMCPServerAgentError
        return linked_agent.id

    existing_agent = agent_repository.get_agent_by_name(db, mcp_server.name)
    if existing_agent is not None:
        return existing_agent.id

    agent_create = AgentCreate(
        name=mcp_server.name,
        description=f"Agent linked to MCP server {mcp_server.name}.",
        owner="system",
        department="MCP",
        risk_level=AgentRiskLevel.MEDIUM,
        status=AgentStatus.DRAFT,
    )
    created_agent = agent_repository.create_agent_pending(
        db,
        agent_create,
    )
    audit_log_service.create_critical_audit_log(
        db,
        AuditLogCreate(
            action=AuditAction.AGENT_CREATED,
            entity_type="agent",
            entity_id=created_agent.id,
            before=None,
            after=agent_service.serialize_agent(created_agent),
        ),
    )
    return created_agent.id


def validate_unique_name(db: Session, name: str) -> None:
    if mcp_server_repository.get_mcp_server_by_name(db, name) is not None:
        raise DuplicateMCPServerNameError


def validate_linked_agent(db: Session, agent_id: UUID | None) -> None:
    if agent_id is not None and agent_repository.get_agent_by_id(db, agent_id) is None:
        raise InvalidMCPServerAgentError
