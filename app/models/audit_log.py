"""Append-only audit trail for sensitive staff-management actions.

Every row records who did what to whom, when, and (optionally) a small
structured detail payload. The table is append-only: no endpoint updates or
deletes rows. Actor identity is snapshotted (id + phone) so the trail stays
readable even after the actor account is deleted.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_action", "action"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Actor (who performed the action); snapshots survive actor deletion.
    actor_user_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    actor_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Machine-readable action key, e.g. "user.role_change".
    action: Mapped[str] = mapped_column(String(60))
    # Optional target account and a human-readable label for it.
    target_user_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    target_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Small structured payload (e.g. {"from": "receptionist", "to": "doctor"}).
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
