from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.tenancy import get_current_organization_id
from app.models.agent import Agent
from app.models.agent_tool import AgentTool
from app.models.audit_log import AuditAction, AuditLog
from app.models.mcp_server import MCPServer
from app.models.policy_rule import PolicyRule


def list_discovered_tools(
    db: Session,
    *,
    agent_id: UUID | None = None,
    server_id: UUID | None = None,
) -> list[tuple[AgentTool, str, str]]:
    organization_id = get_current_organization_id(db)
    statement = (
        select(AgentTool, Agent.name, MCPServer.name)
        .join(Agent, Agent.id == AgentTool.agent_id)
        .join(MCPServer, MCPServer.id == AgentTool.discovered_from_mcp_server_id)
        .where(
            AgentTool.organization_id == organization_id,
            AgentTool.deleted_at.is_(None),
            AgentTool.discovered_from_mcp_server_id.is_not(None),
            Agent.deleted_at.is_(None),
            MCPServer.deleted_at.is_(None),
        )
        .order_by(AgentTool.created_at.desc())
    )
    if agent_id is not None:
        statement = statement.where(AgentTool.agent_id == agent_id)
    if server_id is not None:
        statement = statement.where(AgentTool.discovered_from_mcp_server_id == server_id)
    return [
        (tool, agent_name, server_name)
        for tool, agent_name, server_name in db.execute(statement)
    ]


def list_enabled_policy_rules(db: Session) -> list[PolicyRule]:
    statement = select(PolicyRule).where(
        PolicyRule.organization_id == get_current_organization_id(db),
        PolicyRule.deleted_at.is_(None),
        PolicyRule.is_enabled.is_(True),
    )
    return list(db.scalars(statement).all())


def count_schema_changes_since(db: Session, since: datetime) -> int:
    statement = select(func.count()).select_from(AuditLog).where(
        AuditLog.organization_id == get_current_organization_id(db),
        AuditLog.action == AuditAction.MCP_TOOL_SCHEMA_CHANGED,
        AuditLog.created_at >= since,
    )
    return db.scalar(statement) or 0
