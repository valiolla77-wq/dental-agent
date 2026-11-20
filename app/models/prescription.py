"""Structured prescriptions written on a patient's clinical record.

A prescription is a small header (who prescribed it, when and for which
visit) plus an ordered list of medication lines stored as JSON. Keeping the
lines in one JSON column keeps the record append-only and avoids a second
table for a handful of fields, while still letting the UI render each drug
with its dose and schedule.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Prescription(Base):
    __tablename__ = "prescriptions"
    __table_args__ = (
        Index("ix_prescriptions_patient_created", "patient_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id"), nullable=False, index=True
    )
    doctor_id: Mapped[int | None] = mapped_column(
        ForeignKey("doctors.id"), nullable=True, index=True
    )
    appointment_id: Mapped[int | None] = mapped_column(
        ForeignKey("appointments.id"), nullable=True, index=True
    )
    # [{"name": ..., "dose": ..., "frequency": ..., "duration": ...}, ...]
    items: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    # Soft cancellation keeps the clinical history append-only: a cancelled
    # prescription stays visible with a clear marker instead of disappearing.
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
