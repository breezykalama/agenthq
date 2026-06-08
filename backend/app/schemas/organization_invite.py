from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.organization_invite import OrganizationInviteStatus
from app.models.user import UserRole


class OrganizationInviteCreate(BaseModel):
    email: EmailStr
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    role: UserRole
    expires_in_days: int = Field(default=7, ge=1, le=30)


class OrganizationInviteAccept(BaseModel):
    token: str = Field(min_length=1)
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    password: str = Field(min_length=12, max_length=128)


class OrganizationInviteRead(BaseModel):
    id: UUID
    organization_id: UUID
    email: EmailStr
    full_name: str | None
    role: UserRole
    status: OrganizationInviteStatus
    invited_by_user_id: UUID
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrganizationInviteCreateResponse(OrganizationInviteRead):
    token: str
    invite_url: str


class OrganizationInviteListResponse(BaseModel):
    items: list[OrganizationInviteRead]
    total: int
