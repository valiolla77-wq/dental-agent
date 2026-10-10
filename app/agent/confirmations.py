"""Server-side confirmation records binding an approval to one exact pending write.

The store lives in trusted process memory: only the agent graph issues and
consumes records. AgentState stays untrusted — a forged confirmation_status in
state can never authorize a write without a matching, unconsumed record that
was issued for the same session, tool, and displayed arguments.
"""

from __future__ import annotations

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
    tool_name: str
    arguments: dict[str, Any]
    tool_call_id: str


class ConfirmationStore:
    """Trusted in-process store; one live confirmation per session."""

    def __init__(self) -> None:
        self._records: dict[str, ConfirmationRecord] = {}

    def issue(
        self,
        *,
        session_id: str | None,
        tool_name: str,
        arguments: dict[str, Any],
        tool_call_id: str,
    ) -> ConfirmationRecord:
        # Issuing for a session invalidates any previous pending confirmation.
        self._records = {
            token: record
            for token, record in self._records.items()
            if record.session_id != session_id
        }
        record = ConfirmationRecord(
            token=token_urlsafe(32),
            session_id=session_id,
            tool_name=tool_name,
            arguments=dict(arguments),
            tool_call_id=tool_call_id,
        )
        self._records[record.token] = record
        return record

    def consume(self, token: Any, *, session_id: str | None) -> ConfirmationRecord | None:
        """Pop the record only for the matching session; consumption is final."""
        if not isinstance(token, str) or not token:
            return None
        record = self._records.get(token)
        if record is None or record.session_id != session_id:
            return None
        return self._records.pop(token, None)


confirmation_store = ConfirmationStore()