"""Pydantic schemas for authentication."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginRequest(BaseModel):
    """Request schema for user login."""

    phone: str
    password: str


class TokenResponse(BaseModel):
    """Response schema for access token."""

    access_token: str
    token_type: str = "bearer"

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
            }
        }
    )


class OtpPhone(BaseModel):
    """Shared phone validation for the passwordless patient flow."""

    phone: str

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        cleaned = (value or "").strip()
        digits = "".join(char for char in cleaned if char.isdigit())
        if not 8 <= len(digits) <= 15:
            raise ValueError("شماره تلفن معتبر نیست.")
        return cleaned


class OtpRequest(OtpPhone):
    """Request a one-time code for a phone number."""


class OtpVerifyRequest(OtpPhone):
    """Verify a one-time code."""

    code: str = Field(min_length=4, max_length=12)


class OtpRequestResponse(BaseModel):
    """Uniform acknowledgement; never reveals account state."""

    status: str
    message: str
    dev_otp: str | None = None
    dev_notice: str | None = None


class LinkUserRequest(BaseModel):
    """Staff-assisted link between a patient record and a patient account."""

    phone: str = Field(min_length=8, max_length=20)