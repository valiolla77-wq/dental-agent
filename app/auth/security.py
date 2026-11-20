"""Password hashing and JWT token management."""

from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher

# Token issuer/audience: distinguishing values so a token minted for this
# service can never be replayed against (or accepted from) another service
# that happens to share a signing secret.
JWT_ISSUER = "dental-agent"
JWT_AUDIENCE = "dental-agent-api"

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


async def hash_password_async(password: str) -> str:
    """Hash off the event loop: Argon2id is deliberately CPU/memory heavy."""
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(plain_password: str, password_hash: str) -> bool:
    """Verify off the event loop so one login cannot stall other requests."""
    return await asyncio.to_thread(verify_password, plain_password, password_hash)


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


def password_version(password_hash: str) -> str:
    """Short digest of the current password hash for token invalidation.

    Access tokens for real logins embed this digest (``pwv`` claim). An admin
    password reset changes ``password_hash``, so every outstanding token for
    that account fails the match in ``get_current_user`` and is effectively
    revoked immediately, instead of surviving until its (short) expiry.
    The digest of a hash leaks nothing usable and is compared with
    ``hmac.compare_digest``.
    """
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:16]


def create_access_token(
    *,
    subject: str,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
    password_hash: str | None = None,
) -> str:
    """Create a JWT access token.

    ``password_hash`` is expected for every real authentication flow (login
    and OTP verification); it binds the token to the current credential so a
    reset revokes outstanding tokens. Test/legacy callers may omit it.
    """
    secret = _get_jwt_secret()
    algorithm = _get_jwt_algorithm()

    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(
            minutes=_get_access_token_expire_minutes()
        )

    payload: dict[str, Any] = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(UTC),
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
    }
    if password_hash is not None:
        payload["pwv"] = password_version(password_hash)
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
            options={"require": ["exp", "sub", "iss", "aud"]},
            issuer=JWT_ISSUER,
            audience=JWT_AUDIENCE,
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise ValueError("Token has expired") from None
    except jwt.MissingRequiredClaimError as exc:
        raise ValueError(f"Token missing required claim: {exc}") from exc
    except jwt.InvalidTokenError as exc:
        raise ValueError(f"Invalid token: {exc}") from exc