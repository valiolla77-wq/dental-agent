from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.dental_service import DentalService


APPOINTMENT_SLOT_INDEX = "uq_appointments_doctor_time_scheduled"


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True)

    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id")
    )

    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id")
    )

    service_id: Mapped[int] = mapped_column(
        ForeignKey("dental_services.id"),
        nullable=False,
    )

    appointment_time: Mapped[datetime] = mapped_column(
        DateTime
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="scheduled",
    )

    reason: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    dental_service: Mapped[DentalService] = relationship(
        back_populates="appointments",
    )

    __table_args__ = (
        # Appointments use the doctor's fixed, non-overlapping schedule slots.
        # A cancelled or otherwise non-blocking appointment must not reserve
        # its start time, hence the partial predicate on status.
        Index(
            APPOINTMENT_SLOT_INDEX,
            "doctor_id",
            "appointment_time",
            unique=True,
            sqlite_where=text("status = 'scheduled'"),
        ),
    )
