from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.audit_context import AUDIT_ACTOR_USER_ID
from app.models.agent import AgentRiskLevel
from app.models.agent_tool import AgentTool
from app.models.audit_log import AuditAction, JsonObject
from app.models.governance_alert import (
    GovernanceAlert,
    GovernanceAlertSeverity,
    GovernanceAlertStatus,
    GovernanceAlertType,
)
from app.repositories import governance_alerts as alert_repository
from app.schemas.audit_log import AuditLogCreate
from app.schemas.governance_alert import (
    GovernanceAlertRead,
    GovernanceHealthMetrics,
    GovernanceHealthScore,
)
from app.services import audit_logs as audit_log_service


class GovernanceAlertNotFoundError(Exception):
    pass


class InvalidGovernanceAlertTransitionError(Exception):
    pass


def serialize_alert(alert: GovernanceAlert) -> JsonObject:
    return GovernanceAlertRead.model_validate(alert).model_dump(mode="json")


def audit_alert(
    db: Session,
    action: AuditAction,
    alert: GovernanceAlert,
    *,
    before: JsonObject | None,
) -> None:
    audit_log_service.create_critical_audit_log(
        db,
        AuditLogCreate(
            action=action,
            entity_type="governance_alert",
            entity_id=alert.id,
            before=before,
            after=serialize_alert(alert),
        ),
    )


def create_alert_pending(
    db: Session,
    *,
    alert_type: GovernanceAlertType,
    severity: GovernanceAlertSeverity,
    tool: AgentTool | None,
    mcp_server_id: UUID | None,
    title: str,
    description: str,
    metadata: dict[str, object] | None = None,
) -> GovernanceAlert:
    existing = alert_repository.get_active_alert(
        db,
        alert_type=alert_type,
        tool_id=tool.id if tool else None,
        mcp_server_id=mcp_server_id,
    )
    if existing is not None:
        return existing
    alert = alert_repository.create_alert_pending(
        db,
        alert_type=alert_type,
        severity=severity,
        agent_id=tool.agent_id if tool else None,
        tool_id=tool.id if tool else None,
        mcp_server_id=mcp_server_id,
        title=title,
        description=description,
        metadata=metadata,
    )
    audit_alert(db, AuditAction.GOVERNANCE_ALERT_CREATED, alert, before=None)
    return alert


def create_tool_event_alert_pending(
    db: Session,
    *,
    alert_type: GovernanceAlertType,
    severity: GovernanceAlertSeverity,
    tool: AgentTool,
    title: str,
    description: str,
    metadata: dict[str, object] | None = None,
) -> GovernanceAlert:
    return create_alert_pending(
        db,
        alert_type=alert_type,
        severity=severity,
        tool=tool,
        mcp_server_id=tool.discovered_from_mcp_server_id,
        title=title,
        description=description,
        metadata=metadata,
    )


def resolve_active_alert_pending(
    db: Session,
    *,
    alert_type: GovernanceAlertType,
    tool_id: UUID,
    mcp_server_id: UUID | None,
) -> None:
    alert = alert_repository.get_active_alert(
        db,
        alert_type=alert_type,
        tool_id=tool_id,
        mcp_server_id=mcp_server_id,
    )
    if alert is None:
        return
    before = serialize_alert(alert)
    alert_repository.update_alert_pending(
        db,
        alert,
        {"status": GovernanceAlertStatus.RESOLVED, "resolved_at": datetime.now(UTC)},
    )
    audit_alert(db, AuditAction.GOVERNANCE_ALERT_RESOLVED, alert, before=before)


def reconcile_tool_pending(
    db: Session,
    tool: AgentTool,
    *,
    has_policy: bool,
    policy_coverage_lost: bool = False,
) -> None:
    server_id = tool.discovered_from_mcp_server_id
    high_risk_unreviewed = tool.reviewed_at is None and tool.risk_level in (
        AgentRiskLevel.HIGH,
        AgentRiskLevel.CRITICAL,
    )
    if high_risk_unreviewed:
        create_alert_pending(
            db,
            alert_type=GovernanceAlertType.HIGH_RISK_UNREVIEWED,
            severity=GovernanceAlertSeverity.HIGH,
            tool=tool,
            mcp_server_id=server_id,
            title=f"High-risk tool requires review: {tool.name}",
            description="A high-risk discovered tool has not been reviewed.",
        )
    else:
        resolve_active_alert_pending(
            db,
            alert_type=GovernanceAlertType.HIGH_RISK_UNREVIEWED,
            tool_id=tool.id,
            mcp_server_id=server_id,
        )

    governed = tool.reviewed_at is not None and has_policy
    if not governed:
        create_alert_pending(
            db,
            alert_type=GovernanceAlertType.UNGOVERNED_TOOL,
            severity=GovernanceAlertSeverity.HIGH
            if tool.risk_level in (AgentRiskLevel.HIGH, AgentRiskLevel.CRITICAL)
            else GovernanceAlertSeverity.MEDIUM,
            tool=tool,
            mcp_server_id=server_id,
            title=f"Tool is not governed: {tool.name}",
            description="The discovered tool is not reviewed or has no applicable policy.",
        )
    else:
        resolve_active_alert_pending(
            db,
            alert_type=GovernanceAlertType.UNGOVERNED_TOOL,
            tool_id=tool.id,
            mcp_server_id=server_id,
        )

    if policy_coverage_lost:
        create_alert_pending(
            db,
            alert_type=GovernanceAlertType.POLICY_COVERAGE_LOST,
            severity=GovernanceAlertSeverity.HIGH,
            tool=tool,
            mcp_server_id=server_id,
            title=f"Policy coverage lost: {tool.name}",
            description="A previously governed tool no longer has an applicable policy.",
        )
    elif has_policy:
        resolve_active_alert_pending(
            db,
            alert_type=GovernanceAlertType.POLICY_COVERAGE_LOST,
            tool_id=tool.id,
            mcp_server_id=server_id,
        )


def list_alerts(
    db: Session,
    *,
    status: GovernanceAlertStatus | None,
    severity: GovernanceAlertSeverity | None,
    alert_type: GovernanceAlertType | None,
    tool_id: UUID | None,
    limit: int,
    offset: int,
) -> tuple[list[GovernanceAlert], int]:
    return alert_repository.list_alerts(
        db,
        status=status,
        severity=severity,
        alert_type=alert_type,
        tool_id=tool_id,
        limit=limit,
        offset=offset,
    )


def get_alert(db: Session, alert_id: UUID) -> GovernanceAlert:
    alert = alert_repository.get_alert_by_id(db, alert_id)
    if alert is None:
        raise GovernanceAlertNotFoundError
    return alert


def transition_alert(
    db: Session,
    alert_id: UUID,
    *,
    target_status: GovernanceAlertStatus,
    action: AuditAction,
) -> GovernanceAlert:
    alert = get_alert(db, alert_id)
    if alert.status == target_status:
        raise InvalidGovernanceAlertTransitionError
    if (
        target_status == GovernanceAlertStatus.ACKNOWLEDGED
        and alert.status != GovernanceAlertStatus.OPEN
    ):
        raise InvalidGovernanceAlertTransitionError
    if (
        target_status == GovernanceAlertStatus.RESOLVED
        and alert.status == GovernanceAlertStatus.RESOLVED
    ):
        raise InvalidGovernanceAlertTransitionError
    if (
        target_status == GovernanceAlertStatus.OPEN
        and alert.status != GovernanceAlertStatus.RESOLVED
    ):
        raise InvalidGovernanceAlertTransitionError
    actor_user_id = db.info.get(AUDIT_ACTOR_USER_ID)
    if not isinstance(actor_user_id, UUID):
        raise GovernanceAlertNotFoundError
    before = serialize_alert(alert)
    values: dict[str, object] = {"status": target_status}
    if target_status == GovernanceAlertStatus.ACKNOWLEDGED:
        values.update(
            {
                "acknowledged_by_user_id": actor_user_id,
                "acknowledged_at": datetime.now(UTC),
            }
        )
    elif target_status == GovernanceAlertStatus.RESOLVED:
        values.update({"resolved_by_user_id": actor_user_id, "resolved_at": datetime.now(UTC)})
    else:
        values.update(
            {
                "acknowledged_by_user_id": None,
                "acknowledged_at": None,
                "resolved_by_user_id": None,
                "resolved_at": None,
            }
        )
    alert_repository.update_alert_pending(db, alert, values)
    audit_alert(db, action, alert, before=before)
    db.commit()
    db.refresh(alert)
    return alert


def calculate_health(
    *,
    unreviewed_tools: int,
    high_risk_unreviewed_tools: int,
    ungoverned_tools: int,
    open_alerts: int,
    critical_alerts: int,
    high_alerts: int,
) -> GovernanceHealthScore:
    deductions = (
        unreviewed_tools * 2
        + high_risk_unreviewed_tools * 10
        + ungoverned_tools * 5
        + critical_alerts * 15
        + high_alerts * 8
    )
    score = max(0, min(100, 100 - deductions))
    metrics = GovernanceHealthMetrics(
        unreviewed_tools=unreviewed_tools,
        high_risk_unreviewed_tools=high_risk_unreviewed_tools,
        ungoverned_tools=ungoverned_tools,
        unresolved_critical_alerts=critical_alerts,
        unresolved_high_alerts=high_alerts,
    )
    return GovernanceHealthScore(
        score=score,
        metrics=metrics,
        open_alerts=open_alerts,
        critical_alerts=critical_alerts,
        governance_gaps=unreviewed_tools + ungoverned_tools,
        explanation=(
            "Score starts at 100 and decreases for unreviewed tools, high-risk unreviewed "
            "tools, ungoverned tools, and unresolved high or critical alerts."
        ),
    )


def get_health(db: Session) -> GovernanceHealthScore:
    from app.services import tool_governance as tool_governance_service

    governance = tool_governance_service.get_summary(db)
    tools, _ = tool_governance_service.list_tools(
        db,
        governance_status_filter=None,
        risk_level=None,
        server_id=None,
        agent_id=None,
        limit=200,
        offset=0,
    )
    high_risk_unreviewed = sum(
        tool.governance_status.value == "unreviewed"
        and tool.risk_level in (AgentRiskLevel.HIGH, AgentRiskLevel.CRITICAL)
        for tool in tools
    )
    open_alerts, critical_alerts, high_alerts = alert_repository.get_alert_metrics(db)
    return calculate_health(
        unreviewed_tools=governance.unreviewed_tools,
        high_risk_unreviewed_tools=high_risk_unreviewed,
        ungoverned_tools=governance.total_tools - governance.governed_tools,
        open_alerts=open_alerts,
        critical_alerts=critical_alerts,
        high_alerts=high_alerts,
    )


def covered_tool_ids(db: Session) -> set[UUID]:
    from app.repositories import tool_governance as governance_repository
    from app.services import tool_governance as tool_governance_service

    policies = governance_repository.list_enabled_policy_rules(db)
    return {
        tool.id
        for tool, _, _ in governance_repository.list_discovered_tools(db)
        if tool_governance_service.applicable_policies(tool, policies)
    }


def reconcile_all_tools(db: Session, *, previously_covered: set[UUID] | None = None) -> None:
    from app.repositories import tool_governance as governance_repository
    from app.services import tool_governance as tool_governance_service

    policies = governance_repository.list_enabled_policy_rules(db)
    for tool, _, _ in governance_repository.list_discovered_tools(db):
        has_policy = bool(tool_governance_service.applicable_policies(tool, policies))
        reconcile_tool_pending(
            db,
            tool,
            has_policy=has_policy,
            policy_coverage_lost=bool(
                previously_covered is not None and tool.id in previously_covered and not has_policy
            ),
        )
    db.commit()
