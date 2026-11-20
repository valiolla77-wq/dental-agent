"""Clinical record entries written by clinic staff onto a patient record.

Three kinds of rows live in this table:

- ``treatment``: a performed or planned procedure, optionally pinned to one
  tooth (FDI numbering) and to the appointment during which it happened.
- ``allergy``: a medical alert the patient portal must surface prominently.
- ``note``: any other clinical observation the treating clinician wants to
  keep on the record.

Rows are append-only from the API's point of view: there is no edit or
delete endpoint, so the patient-visible history stays trustworthy. The
patient portal reads these rows only through server-side ownership scoping.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

if TYPE_CHECKING:  # pragma: no cover
    pass

CLINICAL_ENTRY_KINDS: tuple[str, ...] = ("treatment", "allergy", "note")


class ClinicalEntry(Base):
    __tablename__ = "clinical_entries"
    __table_args__ = (
        Index("ix_clinical_entries_patient_created", "patient_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id"), nullable=False, index=True
    )
    # The treating doctor, when known: derived from the linked doctor record
    # for doctor accounts, or picked explicitly by an administrator.
    doctor_id: Mapped[int | None] = mapped_column(
        ForeignKey("doctors.id"), nullable=True, index=True
    )
    appointment_id: Mapped[int | None] = mapped_column(
        ForeignKey("appointments.id"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # FDI two-digit tooth number (11..48) or NULL for whole-mouth entries.
    tooth_fdi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
