from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.audit_context import AUDIT_ACTOR_USER_ID
from app.models.agent import AgentRiskLevel
from app.models.agent_tool import AgentTool
from app.models.audit_log import AuditAction
from app.models.policy_rule import PolicyRule, PolicyRuleScope
from app.repositories import agent_tools as agent_tool_repository
from app.repositories import governance_alerts as alert_repository
from app.repositories import tool_governance as governance_repository
from app.schemas.agent_tool import AgentToolReview
from app.schemas.audit_log import AuditLogCreate
from app.schemas.tool_governance import (
    ToolGovernanceRead,
    ToolGovernanceStatus,
    ToolGovernanceSummary,
)
from app.services import agent_tools as agent_tool_service
from app.services import audit_logs as audit_log_service
from app.services import governance_alerts as alert_service


class DiscoveredToolNotFoundError(Exception):
    pass


def applicable_policies(tool: AgentTool, policies: list[PolicyRule]) -> list[PolicyRule]:
    return [
        rule
        for rule in policies
        if rule.scope == PolicyRuleScope.GLOBAL
        or (rule.scope == PolicyRuleScope.AGENT and rule.agent_id == tool.agent_id)
        or (rule.scope == PolicyRuleScope.TOOL and rule.tool_id == tool.id)
    ]


def governance_status(tool: AgentTool, policies: list[PolicyRule]) -> ToolGovernanceStatus:
    if tool.reviewed_at is None:
        return ToolGovernanceStatus.UNREVIEWED
    if applicable_policies(tool, policies):
        return ToolGovernanceStatus.GOVERNED
    return ToolGovernanceStatus.REVIEWED


def serialize_governance_tool(
    tool: AgentTool,
    agent_name: str,
    server_name: str,
    policies: list[PolicyRule],
    active_alert_ids: list[UUID] | None = None,
) -> ToolGovernanceRead:
    matching = applicable_policies(tool, policies)
    assert tool.discovered_from_mcp_server_id is not None
    return ToolGovernanceRead(
        id=tool.id,
        agent_id=tool.agent_id,
        agent_name=agent_name,
        mcp_server_id=tool.discovered_from_mcp_server_id,
        mcp_server_name=server_name,
        name=tool.name,
        description=tool.description,
        governance_status=governance_status(tool, policies),
        risk_level=tool.risk_level,
        permission=tool.permission,
        is_enabled=tool.is_enabled,
        policy_count=len(matching),
        policy_names=[rule.name for rule in matching],
        governed_by=list(dict.fromkeys(rule.effect for rule in matching)),
        input_schema=tool.input_schema,
        output_schema=tool.output_schema,
        schema_hash=tool.schema_hash,
        schema_version=tool.schema_version,
        schema_last_updated_at=tool.schema_last_updated_at,
        reviewed_by_user_id=tool.reviewed_by_user_id,
        reviewed_at=tool.reviewed_at,
        active_alerts_count=len(active_alert_ids or []),
        active_alert_ids=active_alert_ids or [],
    )


def list_tools(
    db: Session,
    *,
    governance_status_filter: ToolGovernanceStatus | None,
    risk_level: AgentRiskLevel | None,
    server_id: UUID | None,
    agent_id: UUID | None,
    limit: int,
    offset: int,
) -> tuple[list[ToolGovernanceRead], int]:
    policies = governance_repository.list_enabled_policy_rules(db)
    alert_ids = alert_repository.active_alert_ids_by_tool(db)
    items = [
        serialize_governance_tool(tool, agent_name, server_name, policies, alert_ids.get(tool.id))
        for tool, agent_name, server_name in governance_repository.list_discovered_tools(
            db,
            agent_id=agent_id,
            server_id=server_id,
        )
    ]
    if governance_status_filter is not None:
        items = [item for item in items if item.governance_status == governance_status_filter]
    if risk_level is not None:
        items = [item for item in items if item.risk_level == risk_level]
    return items[offset : offset + limit], len(items)


def get_tool(db: Session, tool_id: UUID) -> ToolGovernanceRead:
    policies = governance_repository.list_enabled_policy_rules(db)
    alert_ids = alert_repository.active_alert_ids_by_tool(db)
    for tool, agent_name, server_name in governance_repository.list_discovered_tools(db):
        if tool.id == tool_id:
            return serialize_governance_tool(
                tool,
                agent_name,
                server_name,
                policies,
                alert_ids.get(tool.id),
            )
    raise DiscoveredToolNotFoundError


def review_tool(db: Session, tool_id: UUID, review: AgentToolReview) -> ToolGovernanceRead:
    tool = agent_tool_repository.get_discovered_agent_tool_by_id(db, tool_id)
    if tool is None:
        raise DiscoveredToolNotFoundError
    before = agent_tool_service.serialize_agent_tool(tool)
    old_risk = tool.risk_level
    old_permission = tool.permission
    actor_user_id = db.info.get(AUDIT_ACTOR_USER_ID)
    if not isinstance(actor_user_id, UUID):
        raise DiscoveredToolNotFoundError
    agent_tool_repository.update_agent_tool_pending(
        db,
        tool,
        {
            "risk_level": review.risk_level,
            "permission": review.permission,
            "reviewed_by_user_id": actor_user_id,
            "reviewed_at": datetime.now(UTC),
        },
    )
    after = agent_tool_service.serialize_agent_tool(tool)
    events: list[tuple[AuditAction, dict[str, object] | None]] = [
        (AuditAction.MCP_TOOL_REVIEWED, None)
    ]
    if old_risk != tool.risk_level:
        events.append(
            (
                AuditAction.MCP_TOOL_RISK_CHANGED,
                {"previous": old_risk.value, "new": tool.risk_level.value},
            )
        )
    if old_permission != tool.permission:
        events.append(
            (
                AuditAction.MCP_TOOL_PERMISSION_CHANGED,
                {"previous": old_permission.value, "new": tool.permission.value},
            )
        )
    for action, metadata in events:
        audit_log_service.create_critical_audit_log(
            db,
            AuditLogCreate(
                action=action,
                entity_type="agent_tool",
                entity_id=tool.id,
                before=before,
                after=after,
                metadata=metadata,
            ),
        )
    policies = governance_repository.list_enabled_policy_rules(db)
    alert_service.reconcile_tool_pending(
        db,
        tool,
        has_policy=bool(applicable_policies(tool, policies)),
    )
    db.commit()
    return get_tool(db, tool.id)


def get_summary(db: Session) -> ToolGovernanceSummary:
    policies = governance_repository.list_enabled_policy_rules(db)
    tools = [tool for tool, _, _ in governance_repository.list_discovered_tools(db)]
    statuses = [governance_status(tool, policies) for tool in tools]
    total = len(tools)
    reviewed = sum(status != ToolGovernanceStatus.UNREVIEWED for status in statuses)
    covered = sum(bool(applicable_policies(tool, policies)) for tool in tools)
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    return ToolGovernanceSummary(
        total_tools=total,
        unreviewed_tools=statuses.count(ToolGovernanceStatus.UNREVIEWED),
        reviewed_tools=statuses.count(ToolGovernanceStatus.REVIEWED),
        governed_tools=statuses.count(ToolGovernanceStatus.GOVERNED),
        high_risk_tools=sum(
            tool.risk_level in (AgentRiskLevel.HIGH, AgentRiskLevel.CRITICAL) for tool in tools
        ),
        schema_changes_this_month=governance_repository.count_schema_changes_since(db, month_start),
        risk_distribution={
            risk.value: sum(tool.risk_level == risk for tool in tools) for risk in AgentRiskLevel
        },
        review_coverage=0.0 if total == 0 else round(reviewed * 100 / total, 2),
        policy_coverage=0.0 if total == 0 else round(covered * 100 / total, 2),
    )
