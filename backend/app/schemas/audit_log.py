from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.audit_log import AuditAction, JsonObject


class AuditLogCreate(BaseModel):
    organization_id: UUID | None = None
    actor: str = "system"
    action: AuditAction
    entity_type: str
    entity_id: UUID
    before: JsonObject | None = None
    after: JsonObject | None = None


class AuditLogRead(BaseModel):
    id: UUID
    organization_id: UUID | None
    actor: str
    action: AuditAction
    entity_type: str
    entity_id: UUID
    before: JsonObject | None
    after: JsonObject | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditLogListResponse(BaseModel):
    items: list[AuditLogRead]
    total: int
