"""Server-side confirmation records binding an approval to one exact pending write.

The store lives in trusted process memory: only the agent graph issues and
consumes records. AgentState stays untrusted — a forged confirmation_status in
state can never authorize a write without a matching, unconsumed record that
was issued for the same session, tool, and displayed arguments.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from secrets import token_urlsafe
from typing import Any, Literal, TypedDict


class ConfirmationDecision(TypedDict, total=False):
    """Host-supplied confirmation input delivered via AgentContext, not state."""

    token: str
    decision: Literal["approved", "rejected"]


@dataclass(frozen=True)
class ConfirmationRecord:
    token: str
    session_id: str | None
    user_id: int | None
    tool_name: str
    arguments: dict[str, Any]
    tool_call_id: str
    expires_at: float


def _default_ttl_seconds() -> int:
    try:
        return max(1, int(os.getenv("CONFIRMATION_TTL_SECONDS", "300")))
    except ValueError:
        return 300


class ConfirmationStore:
    """Trusted in-process store; one live confirmation per session."""

    def __init__(self) -> None:
        self._records: dict[str, ConfirmationRecord] = {}

    def issue(
        self,
        *,
        session_id: str | None,
        user_id: int | None,
        tool_name: str,
        arguments: dict[str, Any],
        tool_call_id: str,
        ttl_seconds: int | None = None,
    ) -> ConfirmationRecord:
        # Issuing for a session invalidates any previous pending confirmation
        # and drops expired records so the store stays bounded.
        now = time.monotonic()
        self._records = {
            token: record
            for token, record in self._records.items()
            if record.session_id != session_id and record.expires_at > now
        }
        ttl = ttl_seconds if ttl_seconds is not None else _default_ttl_seconds()
        record = ConfirmationRecord(
            token=token_urlsafe(32),
            session_id=session_id,
            user_id=user_id,
            tool_name=tool_name,
            arguments=dict(arguments),
            tool_call_id=tool_call_id,
            expires_at=now + max(1, ttl),
        )
        self._records[record.token] = record
        return record

    def consume(
        self, token: Any, *, session_id: str | None, user_id: int | None
    ) -> ConfirmationRecord | None:
        """Pop the record only for the matching session and user (single-use).

        An expired record is discarded before authorization. A mismatch never
        mutates the store, so the rightful session keeps its own record.
        """
        if not isinstance(token, str) or not token:
            return None
        record = self._records.get(token)
        if record is None:
            return None
        if time.monotonic() > record.expires_at:
            self._records.pop(token, None)
            return None
        if record.session_id != session_id or record.user_id != user_id:
            return None
        return self._records.pop(token, None)


confirmation_store = ConfirmationStore()