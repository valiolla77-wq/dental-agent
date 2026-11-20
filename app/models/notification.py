"""In-app notifications delivered to a user account's bell menu.

One row per recipient account. Staff actions on a patient's appointments
notify the owning patient account; patient self-service actions notify the
clinic's admin/receptionist accounts. Appointment reminders for the next 24
hours are synthesised lazily (idempotently) when a patient lists their
notifications, so no background scheduler is required.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

NOTIFICATION_KINDS: tuple[str, ...] = (
    "appointment_booked",
    "appointment_cancelled",
    "appointment_rescheduled",
    "reminder",
    "clinical_entry",
    "system",
)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_read", "user_id", "is_read"),
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Soft reference to the related appointment; kept nullable and unenforced
    # on purpose so notification history survives appointment lifecycle moves.
    appointment_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
