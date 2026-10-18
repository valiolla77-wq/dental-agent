"""Persisted, server-side confirmation records for agent write operations.

A pending write is stored in ``agent_confirmations`` and is keyed by the
authenticated ``user_id`` and the client-visible ``session_id``. Only an
HMAC-SHA256 hash of the confirmation token is persisted; the raw token is
returned to the client once at issue time.

Consumption is a conditional, single-row UPDATE so exactly one concurrent
request can consume an unexpired record. Consumption is committed before the
tool runs, making a replay unable to execute the same operation twice. If the
tool fails after consumption the token stays burned; the client must start a
new write request rather than retrying the old token.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from typing import Any, Literal, TypedDict

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.models.agent_confirmation import AgentConfirmation


class ConfirmationDecision(TypedDict, total=False):
    """Host-supplied confirmation input delivered via AgentContext, not state."""

    token: str
    decision: Literal["approved", "rejected"]


@dataclass(frozen=True)
class ConfirmationRecord:
    id: int
    user_id: int
    session_id: str
    tool_name: str
    arguments: dict[str, Any]
    tool_call_id: str
    expires_at: datetime
    decision: str | None = None
    # Populated only for a freshly issued record; never read back from storage.
    token: str | None = None


def _utcnow() -> datetime:
    """Naive-UTC, matching the OTP and appointment datetime convention."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _default_ttl_seconds() -> int:
    try:
        return max(1, int(os.getenv("CONFIRMATION_TTL_SECONDS", "300")))
    except ValueError:
        return 300


def _get_confirmation_secret() -> str:
    """Dedicated HMAC key; fail closed when it is missing."""
    secret = os.getenv("CONFIRMATION_HMAC_SECRET")
    if not secret:
        raise RuntimeError(
            "CONFIRMATION_HMAC_SECRET environment variable is not set. "
            "Agent confirmations cannot be issued without a dedicated secret."
        )
    return secret


def _token_hash(token: str) -> str:
    return hmac.new(
        _get_confirmation_secret().encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _to_record(
    row: AgentConfirmation, *, token: str | None = None
) -> ConfirmationRecord:
    return ConfirmationRecord(
        id=row.id,
        user_id=row.user_id,
        session_id=row.session_id,
        tool_name=row.tool_name,
        arguments=dict(row.arguments or {}),
        tool_call_id=row.tool_call_id,
        expires_at=row.expires_at,
        decision=row.decision,
        token=token,
    )


class ConfirmationStore:
    """Async repository over the persisted confirmation table."""

    async def issue(
        self,
        db: AsyncSession,
        *,
        session_id: str | None,
        user_id: int | None,
        tool_name: str,
        arguments: dict[str, Any],
        tool_call_id: str,
        ttl_seconds: int | None = None,
    ) -> ConfirmationRecord:
        """Create a new pending confirmation, replacing the session's old one."""
        if user_id is None:
            raise AppError("COMMON_UNAUTHORIZED")
        normalized_session = session_id or ""

        token = token_urlsafe(32)
        now = _utcnow()
        ttl = ttl_seconds if ttl_seconds is not None else _default_ttl_seconds()
        expires_at = now + timedelta(seconds=max(1, ttl))
        hashed = _token_hash(token)

        # Invalidate the previous proposal for this user/session and drop
        # expired rows so the table stays bounded.
        await db.execute(
            delete(AgentConfirmation).where(
                AgentConfirmation.user_id == user_id,
                AgentConfirmation.session_id == normalized_session,
            )
        )
        await db.execute(
            delete(AgentConfirmation).where(
                AgentConfirmation.expires_at <= now
            )
        )

        row = AgentConfirmation(
            user_id=user_id,
            session_id=normalized_session,
            tool_name=tool_name,
            arguments=dict(arguments),
            tool_call_id=tool_call_id,
            token_hash=hashed,
            created_at=now,
            expires_at=expires_at,
            consumed_at=None,
            decision=None,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return _to_record(row, token=token)

    async def load_active(
        self,
        db: AsyncSession,
        token: str,
        *,
        session_id: str | None,
        user_id: int | None,
    ) -> ConfirmationRecord | None:
        """Load an unexpired, unconsumed record bound to this user/session/token.

        A mismatch never mutates or deletes the owner's record, so a foreign
        approval attempt cannot invalidate it.
        """
        if not isinstance(token, str) or not token or user_id is None:
            return None
        now = _utcnow()
        try:
            hashed = _token_hash(token)
        except RuntimeError:
            return None

        result = await db.execute(
            select(AgentConfirmation).where(
                AgentConfirmation.user_id == user_id,
                AgentConfirmation.session_id == (session_id or ""),
                AgentConfirmation.token_hash == hashed,
                AgentConfirmation.consumed_at.is_(None),
                AgentConfirmation.expires_at > now,
            )
        )
        row = result.scalar_one_or_none()
        return _to_record(row) if row is not None else None

    async def consume(
        self,
        db: AsyncSession,
        token: str | None,
        *,
        session_id: str | None,
        user_id: int | None,
        decision: Literal["approved", "rejected"],
    ) -> ConfirmationRecord | None:
        """Atomically mark exactly one unexpired record consumed.

        Returns None if no matching unexpired/unconsumed row was changed. The
        conditional UPDATE is the replay and cross-request race barrier.
        """
        if not isinstance(token, str) or not token or user_id is None:
            return None
        normalized_session = session_id or ""
        now = _utcnow()
        try:
            hashed = _token_hash(token)
        except RuntimeError:
            return None

        result = await db.execute(
            select(AgentConfirmation).where(
                AgentConfirmation.user_id == user_id,
                AgentConfirmation.session_id == normalized_session,
                AgentConfirmation.token_hash == hashed,
                AgentConfirmation.consumed_at.is_(None),
                AgentConfirmation.expires_at > now,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        record = _to_record(row)

        changed = await db.execute(
            update(AgentConfirmation)
            .where(
                AgentConfirmation.id == row.id,
                AgentConfirmation.user_id == user_id,
                AgentConfirmation.session_id == normalized_session,
                AgentConfirmation.token_hash == hashed,
                AgentConfirmation.consumed_at.is_(None),
                AgentConfirmation.expires_at > now,
            )
            .values(consumed_at=now, decision=decision)
        )
        if changed.rowcount != 1:
            # Another request consumed or expired the record first. Do not
            # touch it further; the caller treats this as invalid/rejected.
            return None

        await db.commit()
        return ConfirmationRecord(
            id=record.id,
            user_id=record.user_id,
            session_id=record.session_id,
            tool_name=record.tool_name,
            arguments=record.arguments,
            tool_call_id=record.tool_call_id,
            expires_at=record.expires_at,
            decision=decision,
            token=None,
        )

    async def invalidate(
        self,
        db: AsyncSession,
        *,
        session_id: str | None,
        user_id: int | None,
    ) -> None:
        """Remove the session's pending confirmation, if any."""
        if user_id is None:
            return
        await db.execute(
            delete(AgentConfirmation).where(
                AgentConfirmation.user_id == user_id,
                AgentConfirmation.session_id == (session_id or ""),
            )
        )
        await db.commit()

    async def purge_expired(self, db: AsyncSession) -> int:
        """Delete expired records; safe to call opportunistically."""
        result = await db.execute(
            delete(AgentConfirmation).where(
                AgentConfirmation.expires_at <= _utcnow()
            )
        )
        await db.commit()
        return int(result.rowcount or 0)


confirmation_store = ConfirmationStore()
