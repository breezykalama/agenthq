from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole


class OrganizationBootstrapRequest(BaseModel):
    organization_name: str = Field(min_length=1, max_length=255)
    admin_full_name: str = Field(min_length=1, max_length=255)
    admin_email: EmailStr
    admin_password: str = Field(min_length=12, max_length=128)


class OrganizationRead(BaseModel):
    id: UUID
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrganizationMembershipRead(BaseModel):
    id: UUID
    organization_id: UUID
    user_id: UUID
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime
    organization: OrganizationRead
