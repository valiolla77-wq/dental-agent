"""Per-tooth condition map used by the patient dental chart.

One row per (patient, tooth). Teeth without a row are healthy by
construction, so the chart renders a full 32-tooth FDI map from a sparse
table. Statuses are written only by clinic staff with the clinical write
permission; patients see them read-only.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Chart palette semantics:
# - ``treated``: the tooth has been restored/treated.
# - ``needs_treatment``: flagged for a future visit.
# - ``extracted``: no longer present in the mouth.
# - ``healthy``: explicit reset back to normal.
TOOTH_STATUSES: tuple[str, ...] = (
    "healthy",
    "treated",
    "needs_treatment",
    "extracted",
)


def is_valid_tooth_fdi(value: int) -> bool:
    """Permanent-teeth FDI numbering: quadrants 1-4, teeth 1-8 (11..48)."""
    if not isinstance(value, int) or isinstance(value, bool):
        return False
    quadrant, tooth = divmod(value, 10)
    return quadrant in (1, 2, 3, 4) and 1 <= tooth <= 8


class ToothStatus(Base):
    __tablename__ = "tooth_statuses"
    __table_args__ = (
        UniqueConstraint(
            "patient_id",
            "tooth_fdi",
            name="uq_tooth_statuses_patient_tooth",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id"), nullable=False, index=True
    )
    tooth_fdi: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
