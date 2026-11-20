"""Pydantic schemas for authentication."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginRequest(BaseModel):
    """Request schema for user login.

    ``portal`` declares which door the caller used: ``patient`` rejects
    staff accounts, ``staff`` rejects patient accounts. Omitted portal keeps
    the legacy behaviour (any active account may log in) for API
    compatibility; the bundled web app always sends an explicit portal.
    """

    phone: str
    password: str
    portal: Literal["patient", "staff"] | None = None


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


class OtpChannelResponse(BaseModel):
    """Public descriptor of the OTP delivery channel for the login screen.

    Deliberately free of any account or phone state: it only names the
    configured provider and, for the Bale channel, the bot's public deep
    link so patients can open the bot without hunting for it.
    """

    provider: str
    bot_username: str | None = None
    bot_url: str | None = None


class LinkUserRequest(BaseModel):
    """Staff-assisted link between a patient/doctor record and an account."""

    phone: str = Field(min_length=8, max_length=20)


class MeLinkInfo(BaseModel):
    """The authenticated account's own linked clinic record, if any.

    Only present when the account is linked; ids stay inside the caller's
    own scope and are used for navigation, not shown as data to users.
    """

    id: int
    full_name: str
    is_account_holder: bool = False


class MeResponse(BaseModel):
    """Profile of the token holder; the UI's role-awareness source."""

    full_name: str
    phone: str
    role: str
    is_active: bool
    # ``patient`` is the primary record for backwards compatibility;
    # ``patients`` is the complete set owned by the account.
    patient: MeLinkInfo | None = None
    patients: list[MeLinkInfo] = Field(default_factory=list)
    doctor: MeLinkInfo | None = None