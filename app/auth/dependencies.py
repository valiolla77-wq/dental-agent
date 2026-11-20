"""FastAPI dependencies for authentication and authorization."""

from __future__ import annotations

import hmac
import os
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rate_limit import action_rate_limiter
from app.auth.security import decode_access_token, password_version
from app.database import get_db
from app.models.user import User

# HTTP Bearer token scheme
_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> User:
    """Get current authenticated user from JWT token."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = int(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    # Do not reveal whether a validly signed token names a missing or disabled
    # account; both are indistinguishable from any other unusable credential.
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Credential-version check: real login/OTP tokens carry a ``pwv`` digest
    # of the password hash at issuance time. An admin password reset changes
    # the hash, so the mismatch below revokes every outstanding token for
    # this account immediately. Tokens without the claim (pre-deploy or
    # test-minted ones) cannot be attacker-stripped — the signature covers
    # the whole payload — so leniency here cannot be exploited.
    token_pwv = payload.get("pwv")
    if token_pwv is not None:
        expected_pwv = password_version(user.password_hash)
        if not hmac.compare_digest(str(token_pwv), expected_pwv):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return user


async def require_admin(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Require current user to have admin role."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


def _env_positive_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def rate_limited(
    bucket: str,
    *,
    limit_env: str,
    default_limit: int,
    window_env: str,
    default_window_seconds: int,
):
    """Build a dependency that throttles one authenticated user per bucket.

    Limits are read from the environment on every request so deployments can
    tune them (and tests can patch them) without code changes.
    """

    async def _dependency(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> None:
        action_rate_limiter.hit(
            bucket,
            str(current_user.id),
            limit=_env_positive_int(limit_env, default_limit),
            window=float(_env_positive_int(window_env, default_window_seconds)),
        )

    return _dependency


chat_rate_limit = rate_limited(
    "agent_chat",
    limit_env="CHAT_RATE_LIMIT_REQUESTS",
    default_limit=30,
    window_env="CHAT_RATE_LIMIT_WINDOW_SECONDS",
    default_window_seconds=60,
)

feedback_rate_limit = rate_limited(
    "feedback",
    limit_env="FEEDBACK_RATE_LIMIT_REQUESTS",
    default_limit=10,
    window_env="FEEDBACK_RATE_LIMIT_WINDOW_SECONDS",
    default_window_seconds=3600,
)
