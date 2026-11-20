"""Multi-session treatment plan items for a patient record.

Each row is one planned procedure, optionally pinned to a tooth (FDI). The
status moves ``planned -> in_progress -> completed`` (or ``cancelled``) as the
clinic executes the plan, which gives the patient dossier a real treatment
roadmap instead of free-text notes.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

TREATMENT_PLAN_STATUSES: tuple[str, ...] = (
    "planned",
    "in_progress",
    "completed",
    "cancelled",
)


class TreatmentPlanItem(Base):
    __tablename__ = "treatment_plan_items"
    __table_args__ = (
        Index(
            "ix_treatment_plan_items_patient_status",
            "patient_id",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id"), nullable=False, index=True
    )
    doctor_id: Mapped[int | None] = mapped_column(
        ForeignKey("doctors.id"), nullable=True, index=True
    )
    tooth_fdi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="planned"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
