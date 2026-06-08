from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.session import get_session_local
from app.models.agent import Agent, AgentRiskLevel, AgentStatus
from app.models.agent_tool import AgentTool, AgentToolPermission
from app.models.approval import ApprovalStatus
from app.models.execution import ExecutionStatus
from app.models.incident import IncidentStatus
from app.models.policy_rule import PolicyRuleEffect, PolicyRuleScope
from app.repositories import agent_tools as agent_tool_repository
from app.repositories import agents as agent_repository
from app.repositories import policy_rules as policy_rule_repository
from app.schemas.agent import AgentCreate
from app.schemas.agent_tool import AgentToolCreate
from app.schemas.approval import ApprovalCreate, ApprovalDecision
from app.schemas.execution import ExecutionCreate
from app.schemas.incident import IncidentCreate, IncidentDecision
from app.schemas.policy_rule import PolicyRuleCreate
from app.services import agent_tools as agent_tool_service
from app.services import agents as agent_service
from app.services import approvals as approval_service
from app.services import executions as execution_service
from app.services import incidents as incident_service
from app.services import policy_rules as policy_rule_service


def seed_demo_data(db: Session) -> None:
    agents = seed_agents(db)
    tools = seed_tools(db, agents)
    seed_policy_rules(db, agents, tools)
    seed_approvals_executions_and_incidents(db, agents, tools)


def seed_agents(db: Session) -> dict[str, Agent]:
    agent_specs = [
        AgentCreate(
            name="Policy Knowledge Agent",
            description="Answers internal policy and compliance questions.",
            owner="governance-team",
            department="Risk",
            risk_level=AgentRiskLevel.MEDIUM,
            status=AgentStatus.ACTIVE,
        ),
        AgentCreate(
            name="Customer Response Agent",
            description="Drafts customer support responses for review.",
            owner="support-ops",
            department="Customer Support",
            risk_level=AgentRiskLevel.MEDIUM,
            status=AgentStatus.ACTIVE,
        ),
        AgentCreate(
            name="Payment Operations Agent",
            description="Assists with payment operations triage and reconciliation.",
            owner="payments-team",
            department="Finance",
            risk_level=AgentRiskLevel.HIGH,
            status=AgentStatus.ACTIVE,
        ),
        AgentCreate(
            name="Escalation Agent",
            description="Routes urgent issues to the right operational owner.",
            owner="operations",
            department="Operations",
            risk_level=AgentRiskLevel.HIGH,
            status=AgentStatus.ACTIVE,
        ),
    ]
    agents: dict[str, Agent] = {}
    for agent_create in agent_specs:
        agent = agent_repository.get_agent_by_name(db, agent_create.name)
        if agent is None:
            agent = agent_service.create_agent(db, agent_create)
        agents[agent.name] = agent
    return agents


def seed_tools(
    db: Session,
    agents: dict[str, Agent],
) -> dict[tuple[str, str], AgentTool]:
    tool_specs = {
        "Policy Knowledge Agent": [
            ("policy_search", "Search internal policy documents.", AgentToolPermission.READ, "low"),
            ("policy_summary", "Summarize policy sections.", AgentToolPermission.EXECUTE, "medium"),
        ],
        "Customer Response Agent": [
            ("crm_lookup", "Look up customer case context.", AgentToolPermission.READ, "low"),
            ("draft_response", "Draft a customer response.", AgentToolPermission.EXECUTE, "medium"),
        ],
        "Payment Operations Agent": [
            ("payment_lookup", "Look up payment status.", AgentToolPermission.READ, "medium"),
            ("refund_review", "Prepare refund review notes.", AgentToolPermission.EXECUTE, "high"),
        ],
        "Escalation Agent": [
            ("ticket_lookup", "Review escalation ticket details.", AgentToolPermission.READ, "low"),
            ("pager_draft", "Draft an escalation notification.", AgentToolPermission.WRITE, "high"),
        ],
    }
    seeded_tools: dict[tuple[str, str], AgentTool] = {}
    for agent_name, specs in tool_specs.items():
        agent = agents[agent_name]
        for name, description, permission, risk_level in specs:
            tool = agent_tool_repository.get_agent_tool_by_name(db, agent.id, name)
            if tool is None:
                tool = agent_tool_service.create_agent_tool(
                    db,
                    agent.id,
                    AgentToolCreate(
                        name=name,
                        description=description,
                        permission=permission,
                        risk_level=AgentRiskLevel(risk_level),
                    ),
                )
            seeded_tools[(agent_name, name)] = tool
    return seeded_tools


def seed_policy_rules(
    db: Session,
    agents: dict[str, Agent],
    tools: dict[tuple[str, str], AgentTool],
) -> None:
    payment_agent = agents["Payment Operations Agent"]
    customer_agent = agents["Customer Response Agent"]
    seed_policy_rule(
        db,
        PolicyRuleCreate(
            name="Global high-risk requires approval",
            description="High-risk actions require a human approval.",
            scope=PolicyRuleScope.GLOBAL,
            risk_level=AgentRiskLevel.HIGH,
            effect=PolicyRuleEffect.REQUIRE_APPROVAL,
            priority=100,
        ),
    )
    seed_policy_rule(
        db,
        PolicyRuleCreate(
            name="Global critical-risk blocks",
            description="Critical-risk actions are blocked in demo governance mode.",
            scope=PolicyRuleScope.GLOBAL,
            risk_level=AgentRiskLevel.CRITICAL,
            effect=PolicyRuleEffect.BLOCK,
            priority=10,
        ),
    )
    seed_policy_rule(
        db,
        PolicyRuleCreate(
            name="Payment Operations Agent high-risk requires approval",
            description="Payment operations high-risk actions need approval.",
            scope=PolicyRuleScope.AGENT,
            agent_id=payment_agent.id,
            risk_level=AgentRiskLevel.HIGH,
            effect=PolicyRuleEffect.REQUIRE_APPROVAL,
            priority=50,
        ),
    )
    seed_policy_rule(
        db,
        PolicyRuleCreate(
            name="Customer Response Agent low-medium allowed",
            description="Routine customer response drafting is allowed.",
            scope=PolicyRuleScope.AGENT,
            agent_id=customer_agent.id,
            risk_level=AgentRiskLevel.MEDIUM,
            effect=PolicyRuleEffect.ALLOW,
            priority=200,
        ),
    )

    refund_tool = tools[("Payment Operations Agent", "refund_review")]
    seed_policy_rule(
        db,
        PolicyRuleCreate(
            name="Refund review tool high-risk requires approval",
            description="Refund review execution needs explicit approval.",
            scope=PolicyRuleScope.TOOL,
            agent_id=payment_agent.id,
            tool_id=refund_tool.id,
            risk_level=AgentRiskLevel.HIGH,
            effect=PolicyRuleEffect.REQUIRE_APPROVAL,
            priority=25,
        ),
    )


def seed_policy_rule(db: Session, policy_rule_create: PolicyRuleCreate) -> None:
    if policy_rule_repository.get_policy_rule_by_name(db, policy_rule_create.name) is None:
        policy_rule_service.create_policy_rule(db, policy_rule_create)


def seed_approvals_executions_and_incidents(
    db: Session,
    agents: dict[str, Agent],
    tools: dict[tuple[str, str], AgentTool],
) -> None:
    _, existing_executions = execution_service.list_executions(db, limit=1, offset=0)
    if existing_executions > 0:
        return

    payment_agent = agents["Payment Operations Agent"]
    customer_agent = agents["Customer Response Agent"]
    escalation_agent = agents["Escalation Agent"]
    refund_tool = tools[("Payment Operations Agent", "refund_review")]
    draft_tool = tools[("Customer Response Agent", "draft_response")]

    pending_approval = approval_service.create_approval(
        db,
        ApprovalCreate(
            agent_id=payment_agent.id,
            requested_action="refund_review",
            requested_by="payments-team",
            reason="Refund review above demo threshold.",
            risk_level=AgentRiskLevel.HIGH,
        ),
    )
    approved_approval = approval_service.create_approval(
        db,
        ApprovalCreate(
            agent_id=payment_agent.id,
            requested_action="refund_review",
            requested_by="payments-team",
            reason="Approved demo refund workflow.",
            risk_level=AgentRiskLevel.HIGH,
        ),
    )
    approval_service.approve_approval(
        db,
        approved_approval.id,
        ApprovalDecision(
            approver="risk-office",
            decision_reason="Demo controls verified.",
        ),
    )

    execution_service.create_execution(
        db,
        ExecutionCreate(
            agent_id=customer_agent.id,
            tool_id=draft_tool.id,
            action_name="draft_customer_response",
            input_summary="Customer asked about refund policy.",
            output_summary="Drafted a response using approved policy language.",
            status=ExecutionStatus.SUCCEEDED,
            risk_level=AgentRiskLevel.MEDIUM,
            cost_usd=Decimal("0.0300"),
            latency_ms=840,
        ),
    )
    execution_service.create_execution(
        db,
        ExecutionCreate(
            agent_id=payment_agent.id,
            tool_id=refund_tool.id,
            approval_id=approved_approval.id,
            action_name="refund_review",
            input_summary="Review refund exception request.",
            output_summary="Prepared refund review summary.",
            status=ExecutionStatus.SUCCEEDED,
            risk_level=AgentRiskLevel.HIGH,
            cost_usd=Decimal("0.1200"),
            latency_ms=1420,
        ),
    )
    execution_requiring_approval = execution_service.create_execution(
        db,
        ExecutionCreate(
            agent_id=payment_agent.id,
            tool_id=refund_tool.id,
            action_name="refund_review",
            input_summary="Attempted refund review without approval.",
            status=ExecutionStatus.RUNNING,
            risk_level=AgentRiskLevel.HIGH,
            cost_usd=Decimal("0.0500"),
            latency_ms=600,
        ),
    )
    blocked_execution = execution_service.create_execution(
        db,
        ExecutionCreate(
            agent_id=escalation_agent.id,
            action_name="critical_escalation_broadcast",
            input_summary="Attempted critical broadcast.",
            status=ExecutionStatus.RUNNING,
            risk_level=AgentRiskLevel.CRITICAL,
            error_message="Blocked by global critical-risk policy.",
        ),
    )

    incident_service.create_incident(
        db,
        IncidentCreate(
            agent_id=payment_agent.id,
            execution_id=execution_requiring_approval.id,
            title="High-risk payment action awaiting approval",
            description="A payment operation was paused because approval was required.",
            severity=AgentRiskLevel.HIGH,
            status=IncidentStatus.INVESTIGATING,
            reported_by="system",
            assigned_to="payments-team",
        ),
    )
    incident = incident_service.create_incident(
        db,
        IncidentCreate(
            agent_id=escalation_agent.id,
            execution_id=blocked_execution.id,
            title="Critical escalation action blocked",
            description="A critical-risk escalation action was blocked by policy.",
            severity=AgentRiskLevel.CRITICAL,
            reported_by="system",
            assigned_to="operations",
        ),
    )
    incident_service.resolve_incident(
        db,
        incident.id,
        IncidentDecision(resolution_notes="Confirmed expected policy block during demo."),
    )

    if pending_approval.status != ApprovalStatus.PENDING:
        raise RuntimeError("Demo seed expected a pending approval.")


def main() -> None:
    session_local = get_session_local()
    with session_local() as db:
        seed_demo_data(db)
    print("AgentHQ demo seed data is ready.")


if __name__ == "__main__":
    main()
