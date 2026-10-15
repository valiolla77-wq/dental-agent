"""Password hashing and JWT token management."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher

# Use Argon2id for password hashing (argon2-cffi is already a dependency)
# This provides better compatibility than pwdlib 0.3.1
_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a plaintext password."""
    return _password_hasher.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plaintext password against its hash."""
    try:
        return _password_hasher.verify(password_hash, plain_password)
    except Exception:
        return False


def _get_jwt_secret() -> str:
    """Get JWT secret from environment. Raises if not configured."""
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError(
            "JWT_SECRET environment variable is not set. "
            "Authentication cannot proceed without a secret key."
        )
    return secret


def _get_jwt_algorithm() -> str:
    """Get JWT algorithm. Fixed to HS256 for security."""
    return "HS256"


def _get_access_token_expire_minutes() -> int:
    """Get access token expiration in minutes. Default 30 minutes."""
    try:
        return int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    except ValueError:
        return 30


def create_access_token(
    *,
    subject: str,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Create a JWT access token."""
    secret = _get_jwt_secret()
    algorithm = _get_jwt_algorithm()

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=_get_access_token_expire_minutes()
        )

    payload: dict[str, Any] = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, secret, algorithm=algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT access token."""
    secret = _get_jwt_secret()
    algorithm = _get_jwt_algorithm()

    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[algorithm],  # Explicitly specify algorithm, never trust token
            options={"require": ["exp", "sub"]},
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise ValueError("Token has expired")
    except jwt.MissingRequiredClaimError as exc:
        raise ValueError(f"Token missing required claim: {exc}") from exc
    except jwt.InvalidTokenError as exc:
        raise ValueError(f"Invalid token: {exc}") from exc