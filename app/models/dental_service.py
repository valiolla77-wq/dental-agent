from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.doctor_dental_service import doctor_dental_services

if TYPE_CHECKING:
    from app.models.appointment import Appointment
    from app.models.doctor import Doctor


class DentalService(Base):
    __tablename__ = "dental_services"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    doctors: Mapped[list[Doctor]] = relationship(
        secondary=doctor_dental_services,
        back_populates="dental_services",
    )
    appointments: Mapped[list[Appointment]] = relationship(
        back_populates="dental_service",
    )
