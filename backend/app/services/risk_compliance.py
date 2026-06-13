from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenancy import get_current_organization_id
from app.models.agent import AgentRiskLevel
from app.models.agent_tool import AgentTool, AgentToolPermission
from app.models.audit_log import AuditAction
from app.models.governance_alert import GovernanceAlertSeverity, GovernanceAlertType
from app.models.policy_rule import PolicyRule, PolicyRuleEffect, PolicyRuleScope
from app.models.risk_compliance import (
    AIRiskRecord,
    ComplianceControl,
    ComplianceStatus,
    PolicyCoverageStatus,
)
from app.repositories import governance_alerts as alert_repository
from app.repositories import risk_compliance as risk_repository
from app.repositories import tool_governance as governance_repository
from app.schemas.audit_log import AuditLogCreate
from app.schemas.risk_compliance import (
    AIRiskScore,
    ComplianceControlRead,
    ComplianceEvaluation,
    ControlEvaluation,
    RiskFactor,
    RiskRegisterListResponse,
    RiskRegisterRead,
    RiskSnapshotRead,
    RiskSummary,
)
from app.schemas.tool_governance import ToolGovernanceStatus
from app.services import audit_logs as audit_log_service
from app.services import governance_alerts as alert_service
from app.services import tool_governance as governance_service


@dataclass(frozen=True)
class BuiltInControl:
    name: str
    description: str
    severity: AgentRiskLevel


BUILT_IN_CONTROLS = (
    BuiltInControl("CONTROL_001", "All HIGH risk tools require approval.", AgentRiskLevel.HIGH),
    BuiltInControl(
        "CONTROL_002", "All CRITICAL risk tools require approval.", AgentRiskLevel.CRITICAL
    ),
    BuiltInControl("CONTROL_003", "All WRITE tools must be governed.", AgentRiskLevel.HIGH),
    BuiltInControl("CONTROL_004", "All CRITICAL tools must be reviewed.", AgentRiskLevel.CRITICAL),
    BuiltInControl(
        "CONTROL_005", "All enabled tools must have policy coverage.", AgentRiskLevel.HIGH
    ),
)


def ensure_builtin_controls(db: Session) -> list[ComplianceControl]:
    existing = {control.name: control for control in risk_repository.list_controls(db)}
    for built_in in BUILT_IN_CONTROLS:
        if built_in.name in existing:
            continue
        control = risk_repository.create_control(
            db,
            ComplianceControl(
                organization_id=get_current_organization_id(db),
                name=built_in.name,
                description=built_in.description,
                severity=built_in.severity,
                enabled=True,
            ),
        )
        audit_log_service.create_critical_audit_log(
            db,
            AuditLogCreate(
                action=AuditAction.COMPLIANCE_CONTROL_CREATED,
                entity_type="compliance_control",
                entity_id=control.id,
                after={"name": control.name, "severity": control.severity.value, "enabled": True},
            ),
        )
    db.flush()
    return risk_repository.list_controls(db)


def policy_coverage(tool: AgentTool, policies: list[PolicyRule]) -> PolicyCoverageStatus:
    applicable = governance_service.applicable_policies(tool, policies)
    if not applicable:
        return PolicyCoverageStatus.UNCOVERED
    if any(rule.scope in {PolicyRuleScope.AGENT, PolicyRuleScope.TOOL} for rule in applicable):
        return PolicyCoverageStatus.COVERED
    return PolicyCoverageStatus.PARTIALLY_COVERED


def requires_approval(tool: AgentTool, policies: list[PolicyRule]) -> bool:
    return any(
        rule.effect == PolicyRuleEffect.REQUIRE_APPROVAL
        for rule in governance_service.applicable_policies(tool, policies)
        if tool.risk_level.value in risk_levels_at_or_above(rule.risk_level)
    )


def risk_levels_at_or_above(level: AgentRiskLevel) -> set[str]:
    levels = list(AgentRiskLevel)
    return {item.value for item in levels[levels.index(level) :]}


def violated_control_names(
    tool: AgentTool,
    policies: list[PolicyRule],
    governance_status: ToolGovernanceStatus,
) -> list[str]:
    violations: list[str] = []
    approval_required = requires_approval(tool, policies)
    coverage = policy_coverage(tool, policies)
    if tool.risk_level == AgentRiskLevel.HIGH and not approval_required:
        violations.append("CONTROL_001")
    if tool.risk_level == AgentRiskLevel.CRITICAL and not approval_required:
        violations.append("CONTROL_002")
    if (
        tool.permission == AgentToolPermission.WRITE
        and governance_status != ToolGovernanceStatus.GOVERNED
    ):
        violations.append("CONTROL_003")
    if tool.risk_level == AgentRiskLevel.CRITICAL and tool.reviewed_at is None:
        violations.append("CONTROL_004")
    if tool.is_enabled and coverage == PolicyCoverageStatus.UNCOVERED:
        violations.append("CONTROL_005")
    return violations


def compliance_status_for(
    violations: list[str],
    controls: dict[str, ComplianceControl],
) -> ComplianceStatus:
    enabled = [controls[name] for name in violations if name in controls and controls[name].enabled]
    if not enabled:
        return ComplianceStatus.COMPLIANT
    if any(
        control.severity in {AgentRiskLevel.HIGH, AgentRiskLevel.CRITICAL} for control in enabled
    ):
        return ComplianceStatus.NON_COMPLIANT
    return ComplianceStatus.WARNING


def reconcile(db: Session, *, commit: bool = True) -> list[AIRiskRecord]:
    controls = {control.name: control for control in ensure_builtin_controls(db)}
    policies = governance_repository.list_enabled_policy_rules(db)
    discovered = governance_repository.list_discovered_tools(db)
    active_tool_ids: set[UUID] = set()
    records: list[AIRiskRecord] = []
    for tool, _, _ in discovered:
        active_tool_ids.add(tool.id)
        governance = governance_service.governance_status(tool, policies)
        coverage = policy_coverage(tool, policies)
        violations = violated_control_names(tool, policies, governance)
        status = compliance_status_for(violations, controls)
        existing = risk_repository.get_risk_record(db, tool.id)
        record = risk_repository.upsert_risk_record(
            db,
            tool.id,
            {
                "agent_id": tool.agent_id,
                "mcp_server_id": tool.discovered_from_mcp_server_id,
                "risk_level": tool.risk_level,
                "governance_status": governance,
                "policy_coverage_status": coverage,
                "compliance_status": status,
                "owner_user_id": existing.owner_user_id if existing else None,
                "last_reviewed_at": tool.reviewed_at,
            },
        )
        reconcile_compliance_alerts(db, tool, record)
        records.append(record)
    risk_repository.delete_stale_records(db, active_tool_ids)
    if commit:
        db.commit()
    return records


def reconcile_compliance_alerts(db: Session, tool: AgentTool, record: AIRiskRecord) -> None:
    server_id = tool.discovered_from_mcp_server_id
    conditions = (
        (
            GovernanceAlertType.COMPLIANCE_NON_COMPLIANT,
            record.compliance_status == ComplianceStatus.NON_COMPLIANT,
            GovernanceAlertSeverity.HIGH,
            f"Tool is non-compliant: {tool.name}",
            "The tool violates one or more enabled compliance controls.",
        ),
        (
            GovernanceAlertType.CRITICAL_POLICY_COVERAGE_LOST,
            tool.risk_level == AgentRiskLevel.CRITICAL
            and record.policy_coverage_status == PolicyCoverageStatus.UNCOVERED,
            GovernanceAlertSeverity.CRITICAL,
            f"Critical tool has no policy coverage: {tool.name}",
            "A critical tool has no applicable enabled policy.",
        ),
        (
            GovernanceAlertType.CRITICAL_TOOL_UNREVIEWED,
            tool.risk_level == AgentRiskLevel.CRITICAL
            and record.governance_status == ToolGovernanceStatus.UNREVIEWED,
            GovernanceAlertSeverity.CRITICAL,
            f"Critical tool requires review: {tool.name}",
            "A critical tool has not been reviewed.",
        ),
    )
    for alert_type, active, severity, title, description in conditions:
        if active:
            alert_service.create_alert_pending(
                db,
                alert_type=alert_type,
                severity=severity,
                tool=tool,
                mcp_server_id=server_id,
                title=title,
                description=description,
            )
        else:
            alert_service.resolve_active_alert_pending(
                db, alert_type=alert_type, tool_id=tool.id, mcp_server_id=server_id
            )


def build_items(db: Session) -> list[RiskRegisterRead]:
    records = {record.tool_id: record for record in reconcile(db)}
    policies = governance_repository.list_enabled_policy_rules(db)
    items: list[RiskRegisterRead] = []
    for tool, agent_name, server_name in governance_repository.list_discovered_tools(db):
        record = records[tool.id]
        items.append(
            RiskRegisterRead(
                id=record.id,
                tool_id=tool.id,
                tool_name=tool.name,
                agent_id=tool.agent_id,
                agent_name=agent_name,
                mcp_server_id=record.mcp_server_id,
                mcp_server_name=server_name,
                risk_level=record.risk_level,
                governance_status=record.governance_status,
                policy_coverage_status=record.policy_coverage_status,
                compliance_status=record.compliance_status,
                owner_user_id=record.owner_user_id,
                last_reviewed_at=record.last_reviewed_at,
                violated_controls=violated_control_names(tool, policies, record.governance_status),
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )
    return items


def list_risk_register(
    db: Session,
    *,
    risk_level: AgentRiskLevel | None,
    compliance_status: ComplianceStatus | None,
    governance_status: ToolGovernanceStatus | None,
    policy_coverage_status: PolicyCoverageStatus | None,
    limit: int,
    offset: int,
) -> RiskRegisterListResponse:
    items = build_items(db)
    if risk_level is not None:
        items = [item for item in items if item.risk_level == risk_level]
    if compliance_status is not None:
        items = [item for item in items if item.compliance_status == compliance_status]
    if governance_status is not None:
        items = [item for item in items if item.governance_status == governance_status]
    if policy_coverage_status is not None:
        items = [item for item in items if item.policy_coverage_status == policy_coverage_status]
    return RiskRegisterListResponse(items=items[offset : offset + limit], total=len(items))


def evaluate_compliance(
    db: Session,
    *,
    agent_id: UUID | None = None,
    mcp_server_id: UUID | None = None,
    tool_id: UUID | None = None,
) -> ComplianceEvaluation:
    items = build_items(db)
    if agent_id is not None:
        items = [item for item in items if item.agent_id == agent_id]
    if mcp_server_id is not None:
        items = [item for item in items if item.mcp_server_id == mcp_server_id]
    if tool_id is not None:
        items = [item for item in items if item.tool_id == tool_id]
    return evaluate_items(db, items)


def evaluate_items(db: Session, items: list[RiskRegisterRead]) -> ComplianceEvaluation:
    controls = ensure_builtin_controls(db)
    evaluations: list[ControlEvaluation] = []
    for control in controls:
        if not control.enabled:
            continue
        failed = [item for item in items if control.name in item.violated_controls]
        evaluations.append(
            ControlEvaluation(
                control_name=control.name,
                description=control.description,
                severity=control.severity,
                passed_tools=len(items) - len(failed),
                failed_tools=len(failed),
                affected_tool_ids=[item.tool_id for item in failed],
                affected_agent_ids=list(dict.fromkeys(item.agent_id for item in failed)),
            )
        )
    non_compliant = sum(item.compliance_status == ComplianceStatus.NON_COMPLIANT for item in items)
    warning = sum(item.compliance_status == ComplianceStatus.WARNING for item in items)
    score = (
        100
        if not items
        else max(0, round((len(items) - non_compliant - warning * 0.5) * 100 / len(items)))
    )
    status = (
        ComplianceStatus.NON_COMPLIANT
        if non_compliant
        else ComplianceStatus.WARNING
        if warning
        else ComplianceStatus.COMPLIANT
    )
    return ComplianceEvaluation(
        status=status,
        compliance_score=score,
        compliant_tools=len(items) - non_compliant - warning,
        warning_tools=warning,
        non_compliant_tools=non_compliant,
        violated_controls=[item for item in evaluations if item.failed_tools],
    )


def calculate_risk_score(db: Session, items: list[RiskRegisterRead] | None = None) -> AIRiskScore:
    items = build_items(db) if items is None else items
    _, critical_alerts, high_alerts = alert_repository.get_alert_metrics(db)
    metrics = (
        (
            "Critical unreviewed tools",
            sum(
                item.risk_level == AgentRiskLevel.CRITICAL
                and item.governance_status == ToolGovernanceStatus.UNREVIEWED
                for item in items
            ),
            15,
        ),
        (
            "Critical ungoverned tools",
            sum(
                item.risk_level == AgentRiskLevel.CRITICAL
                and item.governance_status != ToolGovernanceStatus.GOVERNED
                for item in items
            ),
            12,
        ),
        (
            "Uncovered tools",
            sum(item.policy_coverage_status == PolicyCoverageStatus.UNCOVERED for item in items),
            5,
        ),
        (
            "Compliance violations",
            sum(item.compliance_status == ComplianceStatus.NON_COMPLIANT for item in items),
            8,
        ),
        ("Unresolved critical alerts", critical_alerts, 10),
        ("Unresolved high alerts", high_alerts, 5),
    )
    factors = [
        RiskFactor(name=name, count=count, deduction=count * weight)
        for name, count, weight in metrics
    ]
    return AIRiskScore(
        score=max(0, 100 - sum(factor.deduction for factor in factors)),
        factors=factors,
        explanation=(
            "Score starts at 100 and decreases for unresolved governance and compliance risk."
        ),
    )


def create_daily_snapshot(db: Session, items: list[RiskRegisterRead], risk_score: int) -> None:
    open_alerts, _, _ = alert_repository.get_alert_metrics(db)
    risk_repository.upsert_snapshot(
        db,
        datetime.now(UTC).date(),
        {
            "risk_score": risk_score,
            "governed_tools": sum(
                item.governance_status == ToolGovernanceStatus.GOVERNED for item in items
            ),
            "ungoverned_tools": sum(
                item.governance_status != ToolGovernanceStatus.GOVERNED for item in items
            ),
            "compliant_tools": sum(
                item.compliance_status == ComplianceStatus.COMPLIANT for item in items
            ),
            "non_compliant_tools": sum(
                item.compliance_status == ComplianceStatus.NON_COMPLIANT for item in items
            ),
            "open_alerts": open_alerts,
        },
    )
    db.commit()


def get_summary(db: Session) -> RiskSummary:
    items = build_items(db)
    compliance = evaluate_items(db, items)
    risk = calculate_risk_score(db, items)
    create_daily_snapshot(db, items, risk.score)
    _, critical_alerts, _ = alert_repository.get_alert_metrics(db)
    return RiskSummary(
        risk_score=risk.score,
        compliance_score=compliance.compliance_score,
        governed_tools=sum(
            item.governance_status == ToolGovernanceStatus.GOVERNED for item in items
        ),
        ungoverned_tools=sum(
            item.governance_status != ToolGovernanceStatus.GOVERNED for item in items
        ),
        compliant_tools=compliance.compliant_tools,
        non_compliant_tools=compliance.non_compliant_tools,
        high_risk_tools=sum(
            item.risk_level in {AgentRiskLevel.HIGH, AgentRiskLevel.CRITICAL} for item in items
        ),
        critical_alerts=critical_alerts,
        compliance_violations=sum(item.failed_tools for item in compliance.violated_controls),
        open_governance_risks=sum(
            item.compliance_status != ComplianceStatus.COMPLIANT for item in items
        ),
        risk_trend=[
            RiskSnapshotRead.model_validate(item)
            for item in reversed(risk_repository.list_snapshots(db))
        ],
    )


def list_controls(db: Session) -> list[ComplianceControlRead]:
    ensure_builtin_controls(db)
    db.commit()
    return [
        ComplianceControlRead.model_validate(control)
        for control in risk_repository.list_controls(db)
    ]
