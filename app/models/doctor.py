from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.doctor_dental_service import doctor_dental_services

if TYPE_CHECKING:
    from app.models.dental_service import DentalService


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(150))
    specialty: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(default=True)

    dental_services: Mapped[list[DentalService]] = relationship(
        secondary=doctor_dental_services,
        back_populates="doctors",
    )
