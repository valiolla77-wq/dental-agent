"""Pydantic schemas for authentication."""

from pydantic import BaseModel, ConfigDict


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