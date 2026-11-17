from pydantic import BaseModel, EmailStr, Field


class EmailVerificationRequest(BaseModel):
    token: str = Field(min_length=32, max_length=512)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class PasswordResetRequest(BaseModel):
    token: str = Field(min_length=32, max_length=512)
    new_password: str = Field(min_length=12, max_length=128)


class IdentityActionResponse(BaseModel):
    message: str
