from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agent import AgentRiskLevel
from app.models.execution import Execution, ExecutionStatus


def create_execution(db: Session, values: dict[str, object]) -> Execution:
    execution = Execution(**values)
    db.add(execution)
    db.commit()
    db.refresh(execution)
    return execution


def create_execution_pending(db: Session, values: dict[str, object]) -> Execution:
    execution = Execution(**values)
    db.add(execution)
    db.flush()
    return execution


def list_executions(
    db: Session,
    *,
    agent_id: UUID | None = None,
    status: ExecutionStatus | None = None,
    risk_level: AgentRiskLevel | None = None,
    approval_id: UUID | None = None,
    limit: int,
    offset: int,
) -> tuple[list[Execution], int]:
    filters = []
    if agent_id is not None:
        filters.append(Execution.agent_id == agent_id)
    if status is not None:
        filters.append(Execution.status == status)
    if risk_level is not None:
        filters.append(Execution.risk_level == risk_level)
    if approval_id is not None:
        filters.append(Execution.approval_id == approval_id)

    statement = (
        select(Execution)
        .where(*filters)
        .order_by(Execution.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    count_statement = select(func.count()).select_from(Execution).where(*filters)

    executions = list(db.scalars(statement).all())
    total = db.scalar(count_statement) or 0
    return executions, total


def get_execution_by_id(db: Session, execution_id: UUID) -> Execution | None:
    statement = select(Execution).where(Execution.id == execution_id)
    return db.scalar(statement)


def update_execution(db: Session, execution: Execution, values: dict[str, object]) -> Execution:
    for field, value in values.items():
        setattr(execution, field, value)

    db.add(execution)
    db.commit()
    db.refresh(execution)
    return execution
