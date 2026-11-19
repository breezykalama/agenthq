from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole
from app.schemas.organization import OrganizationMembershipRead


class UserRegister(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=12, max_length=128)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    role: UserRole | None = None
    is_active: bool | None = None


class UserRead(BaseModel):
    id: UUID
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    email_verified: bool
    email_verified_at: datetime | None
    email_verification_required: bool = False
    created_at: datetime
    updated_at: datetime
    # The selected membership (or the only one). Kept for clients written before multiple
    # memberships; null when the user has none, or several and none is selected.
    organization_membership: OrganizationMembershipRead | None = None
    # Additive (v0.8.2). Populated only for the caller's own identity responses (/auth/me and
    # the bootstrap and invite-acceptance token responses); empty and null in member listings.
    organization_memberships: list[OrganizationMembershipRead] = Field(default_factory=list)
    selected_organization_id: UUID | None = None

    model_config = ConfigDict(from_attributes=True)


class UserListResponse(BaseModel):
    items: list[UserRead]
    total: int


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class BootstrapTokenResponse(TokenResponse):
    user: UserRead
