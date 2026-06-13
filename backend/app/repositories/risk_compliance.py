from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.tenancy import get_current_organization_id
from app.models.risk_compliance import AIRiskRecord, ComplianceControl, RiskSnapshot


def get_risk_record(db: Session, tool_id: UUID) -> AIRiskRecord | None:
    return db.scalar(
        select(AIRiskRecord).where(
            AIRiskRecord.organization_id == get_current_organization_id(db),
            AIRiskRecord.tool_id == tool_id,
        )
    )


def upsert_risk_record(db: Session, tool_id: UUID, values: dict[str, object]) -> AIRiskRecord:
    record = get_risk_record(db, tool_id)
    if record is None:
        record = AIRiskRecord(
            organization_id=get_current_organization_id(db),
            tool_id=tool_id,
            **values,
        )
    else:
        for field, value in values.items():
            setattr(record, field, value)
    db.add(record)
    db.flush()
    return record


def delete_stale_records(db: Session, active_tool_ids: set[UUID]) -> None:
    records = db.scalars(
        select(AIRiskRecord).where(AIRiskRecord.organization_id == get_current_organization_id(db))
    ).all()
    for record in records:
        if record.tool_id not in active_tool_ids:
            db.delete(record)
    db.flush()


def list_records(db: Session) -> list[AIRiskRecord]:
    return list(
        db.scalars(
            select(AIRiskRecord)
            .where(AIRiskRecord.organization_id == get_current_organization_id(db))
            .order_by(AIRiskRecord.updated_at.desc())
        ).all()
    )


def list_controls(db: Session) -> list[ComplianceControl]:
    return list(
        db.scalars(
            select(ComplianceControl)
            .where(ComplianceControl.organization_id == get_current_organization_id(db))
            .order_by(ComplianceControl.name)
        ).all()
    )


def create_control(db: Session, control: ComplianceControl) -> ComplianceControl:
    db.add(control)
    db.flush()
    return control


def get_snapshot(db: Session, snapshot_date: date) -> RiskSnapshot | None:
    return db.scalar(
        select(RiskSnapshot).where(
            RiskSnapshot.organization_id == get_current_organization_id(db),
            RiskSnapshot.date == snapshot_date,
        )
    )


def upsert_snapshot(db: Session, snapshot_date: date, values: dict[str, int]) -> RiskSnapshot:
    snapshot = get_snapshot(db, snapshot_date)
    if snapshot is None:
        snapshot = RiskSnapshot(
            organization_id=get_current_organization_id(db),
            date=snapshot_date,
            **values,
        )
    else:
        for field, value in values.items():
            setattr(snapshot, field, value)
    db.add(snapshot)
    db.flush()
    return snapshot


def list_snapshots(db: Session, *, limit: int = 30) -> list[RiskSnapshot]:
    return list(
        db.scalars(
            select(RiskSnapshot)
            .where(RiskSnapshot.organization_id == get_current_organization_id(db))
            .order_by(RiskSnapshot.date.desc())
            .limit(limit)
        ).all()
    )


def count_records(db: Session) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(AIRiskRecord)
            .where(AIRiskRecord.organization_id == get_current_organization_id(db))
        )
        or 0
    )
