"""Post-visit satisfaction rating submitted by the patient account.

One rating per appointment, appended after the visit time has passed and
only by an account that owns the appointment's patient record. The clinic
dashboard aggregates the average to close the quality feedback loop.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

VISIT_RATING_MIN = 1
VISIT_RATING_MAX = 5


class VisitRating(Base):
    __tablename__ = "visit_ratings"
    __table_args__ = (
        UniqueConstraint("appointment_id", name="uq_visit_ratings_appointment"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id"), nullable=False, index=True
    )
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id"), nullable=False, index=True
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
