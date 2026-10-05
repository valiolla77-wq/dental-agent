from datetime import time

from sqlalchemy import ForeignKey, Integer, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DoctorSchedule(Base):
    __tablename__ = "doctor_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)

    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id")
    )

    day_of_week: Mapped[int] = mapped_column(Integer)

    start_time: Mapped[time] = mapped_column(Time)

    end_time: Mapped[time] = mapped_column(Time)

    slot_duration_minutes: Mapped[int] = mapped_column(
        Integer,
        default=30,
    )

    is_active: Mapped[bool] = mapped_column(
        default=True
    )