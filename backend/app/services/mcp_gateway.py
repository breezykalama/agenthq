import hashlib
import secrets
from datetime import UTC, datetime
from time import monotonic
from uuid import UUID

from sqlalchemy.orm import Session

from app.adapters.mcp_discovery import MCPDiscoveryTarget
from app.adapters.mcp_execution import MCPExecutionAdapter, MCPExecutionError
from app.core.audit_context import AUDIT_ACTOR_ROLE
from app.core.tenancy import get_current_organization_id, set_current_organization_id
from app.models.agent_tool import AgentTool, AgentToolPermission
from app.models.approval import ApprovalStatus
from app.models.audit_log import AuditAction, AuditOutcome
from app.models.execution import Execution, ExecutionStatus
from app.models.mcp_gateway import MCPGatewayCallRecord, MCPGatewayToken, MCPGatewayTokenStatus
from app.models.mcp_server import MCPServer
from app.models.policy_rule import PolicyRuleEffect
from app.repositories import agent_tools as agent_tool_repository
from app.repositories import approvals as approval_repository
from app.repositories import executions as execution_repository
from app.repositories import mcp_gateway as gateway_repository
from app.repositories import mcp_servers as mcp_server_repository
from app.repositories import tool_governance as governance_repository
from app.schemas.audit_log import AuditLogCreate
from app.schemas.execution import ExecutionCreate
from app.schemas.mcp_gateway import (
    MCPGatewayInfo,
    MCPGatewayTokenCreate,
    MCPGatewayTokenCreated,
    MCPGatewayTokenRead,
    MCPGatewayTool,
    MCPGatewayToolCall,
    MCPGatewayToolCallResponse,
    MCPGatewayToolList,
)
from app.schemas.policy_decision import PolicyDecisionResponse
from app.schemas.tool_governance import ToolGovernanceStatus
from app.services import audit_logs as audit_log_service
from app.services import executions as execution_service
from app.services import tool_governance as governance_service

SAFE_UPSTREAM_ERROR = "Upstream MCP tool call failed."


class MCPGatewayNotFoundError(Exception):
    pass


class MCPGatewayTokenInvalidError(Exception):
    pass


class MCPGatewayToolUnavailableError(Exception):
    pass


class MCPGatewayApprovalInvalidError(Exception):
    pass


def hash_gateway_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def generate_gateway_token() -> str:
    return f"aghq_{secrets.token_urlsafe(32)}"


def create_token(db: Session, create: MCPGatewayTokenCreate) -> MCPGatewayTokenCreated:
    server = mcp_server_repository.get_mcp_server_by_id(db, create.mcp_server_id)
    actor_user_id = db.info.get("audit_actor_user_id")
    if server is None or not isinstance(actor_user_id, UUID):
        raise MCPGatewayNotFoundError
    raw_token = generate_gateway_token()
    token = gateway_repository.create_token_pending(
        db,
        MCPGatewayToken(
            organization_id=get_current_organization_id(db),
            mcp_server_id=server.id,
            name=create.name,
            token_hash=hash_gateway_token(raw_token),
            expires_at=create.expires_at,
            created_by_user_id=actor_user_id,
        ),
    )
    audit_gateway_event(
        db,
        action=AuditAction.MCP_GATEWAY_TOKEN_CREATED,
        token=token,
        resource_id=token.id,
    )
    db.commit()
    db.refresh(token)
    return MCPGatewayTokenCreated(
        **MCPGatewayTokenRead.model_validate(token).model_dump(),
        token=raw_token,
    )


def rotate_token(db: Session, token_id: UUID) -> MCPGatewayTokenCreated:
    token = gateway_repository.get_token_by_id(db, token_id)
    if token is None:
        raise MCPGatewayNotFoundError
    raw_token = generate_gateway_token()
    gateway_repository.update_token_pending(
        db,
        token,
        {
            "token_hash": hash_gateway_token(raw_token),
            "status": MCPGatewayTokenStatus.ACTIVE,
        },
    )
    audit_gateway_event(
        db,
        action=AuditAction.MCP_GATEWAY_TOKEN_ROTATED,
        token=token,
        resource_id=token.id,
    )
    db.commit()
    db.refresh(token)
    return MCPGatewayTokenCreated(
        **MCPGatewayTokenRead.model_validate(token).model_dump(),
        token=raw_token,
    )


def revoke_token(db: Session, token_id: UUID) -> MCPGatewayToken:
    token = gateway_repository.get_token_by_id(db, token_id)
    if token is None:
        raise MCPGatewayNotFoundError
    gateway_repository.update_token_pending(
        db,
        token,
        {"status": MCPGatewayTokenStatus.REVOKED},
    )
    audit_gateway_event(
        db,
        action=AuditAction.MCP_GATEWAY_TOKEN_REVOKED,
        token=token,
        resource_id=token.id,
    )
    db.commit()
    db.refresh(token)
    return token


def authenticate_token(
    db: Session,
    raw_token: str,
    mcp_server_id: UUID,
) -> MCPGatewayToken:
    token = gateway_repository.get_token_by_hash(db, hash_gateway_token(raw_token))
    now = datetime.now(UTC)
    if (
        token is None
        or token.status != MCPGatewayTokenStatus.ACTIVE
        or token.mcp_server_id != mcp_server_id
        or (token.expires_at is not None and token.expires_at <= now)
    ):
        raise MCPGatewayTokenInvalidError
    set_current_organization_id(db, token.organization_id)
    db.info[AUDIT_ACTOR_ROLE] = "gateway"
    return token


def gateway_info(db: Session, token: MCPGatewayToken) -> MCPGatewayInfo:
    server = require_server(db, token)
    assert server.agent_id is not None
    return MCPGatewayInfo(
        mcp_server_id=server.id,
        name=server.name,
        status=server.status,
        linked_agent_id=server.agent_id,
        gateway_principal=f"gateway:{token.id}",
    )


def list_gateway_tools(db: Session, token: MCPGatewayToken) -> MCPGatewayToolList:
    server = require_server(db, token)
    policies = governance_repository.list_enabled_policy_rules(db)
    items: list[MCPGatewayTool] = []
    for tool, _, _ in governance_repository.list_discovered_tools(db, server_id=server.id):
        status = governance_service.governance_status(tool, policies)
        if (
            tool.agent_id == server.agent_id
            and tool.is_enabled
            and tool.permission in {AgentToolPermission.EXECUTE, AgentToolPermission.ADMIN}
            and status != ToolGovernanceStatus.UNREVIEWED
        ):
            items.append(
                MCPGatewayTool(
                    id=tool.id,
                    name=tool.name,
                    description=tool.description,
                    input_schema=tool.input_schema,
                    output_schema=tool.output_schema,
                    risk_level=tool.risk_level,
                    permission=tool.permission,
                    governance_status=status,
                )
            )
    audit_gateway_event(
        db,
        action=AuditAction.MCP_GATEWAY_TOOLS_LISTED,
        token=token,
        resource_id=server.id,
        metadata={"tool_count": len(items)},
    )
    gateway_repository.mark_token_used_pending(db, token)
    db.commit()
    return MCPGatewayToolList(items=items, total=len(items))


def call_gateway_tool(
    db: Session,
    token: MCPGatewayToken,
    tool_id: UUID,
    call: MCPGatewayToolCall,
    adapter: MCPExecutionAdapter,
) -> MCPGatewayToolCallResponse:
    server = require_server(db, token)
    assert server.agent_id is not None
    if call.idempotency_key is not None:
        previous = gateway_repository.get_call_record(
            db,
            gateway_token_id=token.id,
            tool_id=tool_id,
            idempotency_key=call.idempotency_key,
        )
        if previous is not None:
            response = MCPGatewayToolCallResponse.model_validate(
                {**previous.response_payload, "idempotent_replay": True}
            )
            audit_gateway_event(
                db,
                action=AuditAction.MCP_GATEWAY_CALL_REQUESTED,
                token=token,
                resource_id=tool_id,
                metadata={
                    "execution_id": str(previous.execution_id),
                    "idempotent_replay": True,
                },
            )
            gateway_repository.mark_token_used_pending(db, token)
            db.commit()
            return response
    tool = require_gateway_tool(db, server.id, server.agent_id, tool_id)
    approval_id = validate_gateway_approval(db, tool.agent_id, tool.name, call.approval_id)
    decision = execution_service.evaluate_policy_decision(
        db,
        ExecutionCreate(
            agent_id=tool.agent_id,
            tool_id=tool.id,
            action_name=tool.name,
            risk_level=tool.risk_level,
        ),
    )
    audit_gateway_event(
        db,
        action=AuditAction.MCP_GATEWAY_CALL_REQUESTED,
        token=token,
        resource_id=tool.id,
        metadata=gateway_metadata(server.id, tool.agent_id, tool.id, call.approval_id),
    )
    status = ExecutionStatus.PENDING
    action = AuditAction.MCP_GATEWAY_CALL_SUCCEEDED
    outcome = AuditOutcome.SUCCESS
    result: dict[str, object] | None = None
    error: str | None = None
    latency_ms: int | None = None
    if decision.decision == PolicyRuleEffect.BLOCK:
        status = ExecutionStatus.BLOCKED
        action = AuditAction.MCP_GATEWAY_CALL_BLOCKED
        outcome = AuditOutcome.DENIED
    elif decision.decision == PolicyRuleEffect.REQUIRE_APPROVAL and approval_id is None:
        status = ExecutionStatus.REQUIRES_APPROVAL
        action = AuditAction.MCP_GATEWAY_CALL_REQUIRES_APPROVAL
        outcome = AuditOutcome.DENIED
    else:
        started = monotonic()
        try:
            result = adapter.call_tool(
                target_for_server(server),
                tool.name,
                call.input_payload,
            ).payload
            status = ExecutionStatus.SUCCEEDED
        except (MCPExecutionError, TimeoutError):
            status = ExecutionStatus.FAILED
            action = AuditAction.MCP_GATEWAY_CALL_FAILED
            outcome = AuditOutcome.FAILED
            error = SAFE_UPSTREAM_ERROR
        latency_ms = round((monotonic() - started) * 1000)
    execution = create_gateway_execution(
        db,
        tool=tool,
        decision=decision,
        status=status,
        approval_id=approval_id,
        latency_ms=latency_ms,
        result=result,
        error=error,
        input_payload=call.input_payload,
    )
    response = MCPGatewayToolCallResponse(
        execution_id=execution.id,
        status=status,
        policy_decision=decision.decision,
        policy_decision_reason=decision.reason,
        approval_id=approval_id,
        result=result,
        error=error,
    )
    audit_gateway_event(
        db,
        action=action,
        token=token,
        resource_id=tool.id,
        outcome=outcome,
        reason=error or decision.reason,
        metadata={
            **gateway_metadata(server.id, tool.agent_id, tool.id, approval_id),
            "execution_id": str(execution.id),
            "status": status.value,
        },
    )
    gateway_repository.mark_token_used_pending(db, token)
    if call.idempotency_key is not None:
        gateway_repository.create_call_record_pending(
            db,
            MCPGatewayCallRecord(
                organization_id=token.organization_id,
                gateway_token_id=token.id,
                tool_id=tool.id,
                execution_id=execution.id,
                idempotency_key=call.idempotency_key,
                response_payload=response.model_dump(mode="json", exclude={"result"}),
            ),
        )
    db.commit()
    return response


def require_server(db: Session, token: MCPGatewayToken) -> MCPServer:
    server = mcp_server_repository.get_mcp_server_by_id(db, token.mcp_server_id)
    if server is None or server.agent_id is None:
        raise MCPGatewayNotFoundError
    return server


def require_gateway_tool(
    db: Session,
    server_id: UUID,
    agent_id: UUID,
    tool_id: UUID,
) -> AgentTool:
    tool = agent_tool_repository.get_agent_tool_by_id(db, agent_id, tool_id)
    policies = governance_repository.list_enabled_policy_rules(db)
    if (
        tool is None
        or tool.discovered_from_mcp_server_id != server_id
        or not tool.is_enabled
        or tool.permission not in {AgentToolPermission.EXECUTE, AgentToolPermission.ADMIN}
        or governance_service.governance_status(tool, policies) == ToolGovernanceStatus.UNREVIEWED
    ):
        raise MCPGatewayToolUnavailableError
    return tool


def validate_gateway_approval(
    db: Session,
    agent_id: UUID,
    tool_name: str,
    approval_id: UUID | None,
) -> UUID | None:
    if approval_id is None:
        return None
    approval = approval_repository.get_approval_by_id(db, approval_id)
    if (
        approval is None
        or approval.agent_id != agent_id
        or approval.status != ApprovalStatus.APPROVED
        or approval.requested_action != tool_name
    ):
        audit_log_service.record_event(
            db,
            action=AuditAction.SECURITY_ACCESS_DENIED,
            resource_type="approval",
            resource_id=approval_id,
            outcome=AuditOutcome.DENIED,
            reason="Approval was invalid for the requested gateway tool call.",
            metadata={"attempted_action": "mcp_gateway.call"},
            actor="gateway",
        )
        raise MCPGatewayApprovalInvalidError
    return approval.id


def create_gateway_execution(
    db: Session,
    *,
    tool: AgentTool,
    decision: PolicyDecisionResponse,
    status: ExecutionStatus,
    approval_id: UUID | None,
    latency_ms: int | None,
    result: dict[str, object] | None,
    error: str | None,
    input_payload: dict[str, object],
) -> Execution:
    completed_at = (
        datetime.now(UTC)
        if status in {ExecutionStatus.SUCCEEDED, ExecutionStatus.FAILED, ExecutionStatus.BLOCKED}
        else None
    )
    execution = execution_repository.create_execution_pending(
        db,
        {
            "agent_id": tool.agent_id,
            "tool_id": tool.id,
            "action_name": tool.name,
            "input_summary": summarize_input(input_payload),
            "output_summary": summarize_output(result),
            "status": status,
            "risk_level": tool.risk_level,
            "approval_id": approval_id,
            "policy_decision": decision.decision,
            "policy_decision_reason": decision.reason,
            "policy_rule_id": decision.matched_rule_id,
            "latency_ms": latency_ms,
            "error_message": error,
            "completed_at": completed_at,
        },
    )
    audit_log_service.create_critical_audit_log(
        db,
        AuditLogCreate(
            action=AuditAction.EXECUTION_CREATED,
            entity_type="execution",
            entity_id=execution.id,
            after={
                "id": str(execution.id),
                "agent_id": str(execution.agent_id),
                "tool_id": str(execution.tool_id),
                "action_name": execution.action_name,
                "status": execution.status.value,
                "policy_decision": (
                    execution.policy_decision.value if execution.policy_decision else None
                ),
            },
            outcome=(
                AuditOutcome.FAILED
                if execution.status == ExecutionStatus.FAILED
                else AuditOutcome.SUCCESS
            ),
            metadata={"source": "mcp_gateway"},
        ),
    )
    return execution


def summarize_input(payload: dict[str, object]) -> str:
    return f"Gateway input fields: {', '.join(sorted(payload))}"[:5000]


def summarize_output(payload: dict[str, object] | None) -> str | None:
    if payload is None:
        return None
    return f"Upstream MCP result fields: {', '.join(sorted(payload))}"[:5000]


def target_for_server(server: MCPServer) -> MCPDiscoveryTarget:
    return MCPDiscoveryTarget(
        server_url=server.server_url,
        transport_type=server.transport_type,
        auth_type=server.auth_type,
        auth_secret_ref=server.auth_secret_ref,
        request_timeout_seconds=server.request_timeout_seconds,
        connect_timeout_seconds=server.connect_timeout_seconds,
    )


def gateway_metadata(
    server_id: UUID,
    agent_id: UUID,
    tool_id: UUID,
    approval_id: UUID | None,
) -> dict[str, object]:
    return {
        "mcp_server_id": str(server_id),
        "agent_id": str(agent_id),
        "tool_id": str(tool_id),
        "approval_id": str(approval_id) if approval_id else None,
    }


def audit_gateway_event(
    db: Session,
    *,
    action: AuditAction,
    token: MCPGatewayToken,
    resource_id: UUID,
    outcome: AuditOutcome = AuditOutcome.SUCCESS,
    reason: str | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    audit_log_service.create_critical_audit_log(
        db,
        AuditLogCreate(
            actor=f"gateway:{token.id}",
            action=action,
            entity_type="mcp_gateway",
            entity_id=resource_id,
            outcome=outcome,
            reason=reason,
            metadata={"gateway_token_id": str(token.id), **(metadata or {})},
        ),
    )
