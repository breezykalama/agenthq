from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.models.audit_log import AuditAction, AuditOutcome, JsonObject


class AuditLogCreate(BaseModel):
    organization_id: UUID | None = None
    actor: str = "system"
    actor_user_id: UUID | None = None
    actor_role: str | None = None
    action: AuditAction
    entity_type: str
    entity_id: UUID
    before: JsonObject | None = None
    after: JsonObject | None = None
    outcome: AuditOutcome = AuditOutcome.SUCCESS
    reason: str | None = Field(default=None, max_length=1000)
    request_id: str | None = Field(default=None, max_length=255)
    ip_address: str | None = Field(default=None, max_length=64)
    user_agent: str | None = Field(default=None, max_length=512)
    metadata: JsonObject | None = None


class AuditLogRead(BaseModel):
    id: UUID
    organization_id: UUID | None
    actor: str
    actor_user_id: UUID | None
    actor_role: str | None
    action: AuditAction
    entity_type: str
    entity_id: UUID
    before: JsonObject | None
    after: JsonObject | None
    outcome: AuditOutcome
    reason: str | None
    request_id: str | None
    ip_address: str | None
    user_agent: str | None
    metadata: JsonObject | None = Field(validation_alias="event_metadata")
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def event_id(self) -> UUID:
        return self.id

    @computed_field  # type: ignore[prop-decorator]
    @property
    def timestamp(self) -> datetime:
        return self.created_at

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resource_type(self) -> str:
        return self.entity_type

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resource_id(self) -> UUID:
        return self.entity_id


class AuditLogListResponse(BaseModel):
    items: list[AuditLogRead]
    total: int
