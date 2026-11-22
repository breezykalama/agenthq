"""Risk ordering for approvals: an approval must be at least as risky as what it authorizes."""

from app.models.agent import AgentRiskLevel

RISK_ORDER: dict[AgentRiskLevel, int] = {
    AgentRiskLevel.LOW: 0,
    AgentRiskLevel.MEDIUM: 1,
    AgentRiskLevel.HIGH: 2,
    AgentRiskLevel.CRITICAL: 3,
}


def covering_risk_levels(required: object) -> frozenset[AgentRiskLevel]:
    """Approval risk levels that may authorize an operation of ``required`` risk.

    A missing or unknown required level yields the empty set, so nothing can authorize it.
    """
    if not isinstance(required, AgentRiskLevel) or required not in RISK_ORDER:
        return frozenset()
    floor = RISK_ORDER[required]
    return frozenset(level for level, rank in RISK_ORDER.items() if rank >= floor)


def approval_risk_covers(approval_risk: object, required: object) -> bool:
    return isinstance(approval_risk, AgentRiskLevel) and approval_risk in covering_risk_levels(
        required
    )
