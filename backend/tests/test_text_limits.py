from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from app.schemas.approval import ApprovalCreate, ApprovalDecision
from app.schemas.execution import ExecutionCreate, ExecutionUpdate
from app.schemas.incident import IncidentCreate, IncidentDecision, IncidentUpdate
from app.schemas.mcp_server import MCPServerCreate, MCPServerUpdate


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (
            IncidentCreate,
            {
                "agent_id": uuid4(),
                "title": "Oversized incident",
                "description": "x" * 5001,
                "severity": "high",
            },
        ),
        (IncidentUpdate, {"resolution_notes": "x" * 2001}),
        (IncidentDecision, {"resolution_notes": "x" * 2001}),
        (
            ExecutionCreate,
            {
                "agent_id": uuid4(),
                "action_name": "oversized",
                "input_summary": "x" * 5001,
                "risk_level": "low",
            },
        ),
        (ExecutionUpdate, {"output_summary": "x" * 5001}),
        (ExecutionUpdate, {"error_message": "x" * 2001}),
        (
            MCPServerCreate,
            {
                "name": "Oversized MCP",
                "server_url": "https://mcp.example.com",
                "description": "x" * 5001,
            },
        ),
        (MCPServerUpdate, {"last_error": "x" * 2001}),
        (
            ApprovalCreate,
            {
                "agent_id": uuid4(),
                "requested_action": "oversized",
                "reason": "x" * 2001,
                "risk_level": "high",
            },
        ),
        (ApprovalDecision, {"decision_reason": "x" * 2001}),
    ],
)
def test_high_risk_text_fields_reject_oversized_values(
    schema: type[BaseModel],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        schema.model_validate(payload)
