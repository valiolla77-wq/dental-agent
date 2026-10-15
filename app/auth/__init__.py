"""Authentication module."""

from app.auth.dependencies import get_current_user, require_admin
from app.auth.router import router as auth_router
from app.auth.schemas import LoginRequest, TokenResponse
from app.auth.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

__all__ = [
    "auth_router",
    "get_current_user",
    "require_admin",
    "LoginRequest",
    "TokenResponse",
    "create_access_token",
    "decode_access_token",
    "hash_password",
    "verify_password",
]