from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.dental_service import DentalService


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
