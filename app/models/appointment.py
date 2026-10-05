from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True)

    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id")
    )

    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id")
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