from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ClinicSetting(Base):
    __tablename__ = "clinic_settings"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    max_appointments_per_day: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    max_appointments_per_week: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    max_appointments_per_month: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )