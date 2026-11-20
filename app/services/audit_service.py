"""Append-only audit trail writer for sensitive staff-management actions.

Every helper writes one ``audit_logs`` row in the caller's session/commit
scope so the trail is atomic with the change it describes. Failures of the
audit write therefore fail the whole operation — an unrecorded sensitive
change is treated as worse than a rejected one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.user import User


def _utc_now_naive() -> datetime:
    """Naive UTC timestamp, matching the rest of the codebase."""
    return datetime.now(UTC).replace(tzinfo=None)


def _actor_snapshot(actor: User | None) -> tuple[int | None, str | None]:
    if actor is None:
        return None, None
    return (
        int(actor.id) if actor.id is not None else None,
        getattr(actor, "phone", None),
    )


async def record_audit(
    db: AsyncSession,
    *,
    actor: User | None,
    action: str,
    target_user_id: int | None = None,
    target_label: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Append one audit row inside the caller's transaction.

    The row is flushed (not committed): the endpoint's later ``commit()``
    persists the business change and its audit entry together.
    """
    actor_id, actor_phone = _actor_snapshot(actor)
    db.add(
        AuditLog(
            actor_user_id=actor_id,
            actor_phone=actor_phone,
            action=action,
            target_user_id=target_user_id,
            target_label=target_label[:200] if target_label else None,
            detail=detail,
            created_at=_utc_now_naive(),
        )
    )
    await db.flush()
