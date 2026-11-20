from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.auth.permissions import PERMISSION_ACTIONS, PERMISSION_EFFECTS

StaffRole = Literal["admin", "receptionist", "doctor"]


class UserCreate(BaseModel):
    full_name: str
    phone: str
    password: str = Field(min_length=8, max_length=200)
    role: Literal["admin", "receptionist", "doctor", "patient"] = Field(
        description="Staff role assigned explicitly by an administrator."
    )


class UserUpdate(BaseModel):
    """Admin account-management patch; every field is optional.

    ``role`` may be reassigned, ``is_active`` enables/disables the account,
    and an optional new password is rehashed server-side before storing.
    """

    full_name: str | None = None
    role: Literal["admin", "receptionist", "doctor", "patient"] | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=200)


class UserResponse(BaseModel):
    """Account row for the admin staff table (no password hash ever)."""

    id: int
    full_name: str
    phone: str
    role: str
    is_active: bool
    created_at: datetime | None = None
    last_login_at: datetime | None = None
    permission_overrides: dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)

    @field_validator("permission_overrides", mode="before")
    @classmethod
    def _none_to_empty_dict(cls, value: object) -> object:
        """A NULL/invalid overrides column serialises as an empty dict."""
        if not isinstance(value, dict):
            return {}
        return value


class PermissionActionState(BaseModel):
    """One row of the admin permission matrix for a single account."""

    action: str
    role_default: bool
    override: Literal["allow", "deny"] | None = None
    effective: bool


class UserPermissionsResponse(BaseModel):
    user_id: int
    role: str
    actions: list[PermissionActionState]


class UserPermissionsUpdate(BaseModel):
    """Replace the account's permission overrides wholesale.

    Keys must be catalogued actions; values must be ``allow``/``deny``.
    Sending an empty object clears every override back to role defaults.
    """

    overrides: dict[str, Literal["allow", "deny"]] = Field(default_factory=dict)

    @field_validator("overrides")
    @classmethod
    def validate_actions(cls, value: dict[str, str]) -> dict[str, str]:
        unknown = sorted(set(value) - set(PERMISSION_ACTIONS))
        if unknown:
            raise ValueError(
                "Unknown permission actions: " + ", ".join(unknown)
            )
        for action, effect in value.items():
            if effect not in PERMISSION_EFFECTS:
                raise ValueError(
                    f"Invalid effect for {action}: must be allow or deny."
                )
        return value
