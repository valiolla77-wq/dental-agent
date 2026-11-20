"""Clinic-wide aggregate reports built only from real database rows.

These functions never invent numbers: every value is a SQL ``count`` (or)
grouped count over actual ``appointments``/``patients``/... rows. Windows are
evaluated with the clinic's Asia/Tehran wall-clock time, matching the booking
services, so «امروز» means the same Tehran day everywhere.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.models.appointment import Appointment
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.services.appointment_service import clinic_now

MIN_WINDOW_DAYS = 1
MAX_WINDOW_DAYS = 90
DEFAULT_WINDOW_DAYS = 30


def _validate_window(window_days: int) -> int:
    if not isinstance(window_days, int) or not (
        MIN_WINDOW_DAYS <= window_days <= MAX_WINDOW_DAYS
    ):
        raise AppError("COMMON_VALIDATION_ERROR")
    return window_days


def _day_bounds(current: datetime) -> tuple[datetime, datetime]:
    day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    return day_start, day_start + timedelta(days=1)


async def _count(
    db: AsyncSession, *conditions: object
) -> int:
    query = select(func.count()).select_from(Appointment)
    if conditions:
        query = query.where(*conditions)
    row = await db.execute(query)
    return int(row.scalar_one())


async def clinic_appointments_report(
    db: AsyncSession,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    now: datetime | None = None,
) -> dict[str, object]:
    """Appointment workload summary for the requested forward window.

    Returns counts of real rows only: today's scheduled appointments,
    the upcoming scheduled/cancelled counts inside the window, and a
    per-doctor scheduled breakdown. Cancelled appointments no longer hold
    their slot, so they are reported separately from the scheduled load.
    """
    window_days = _validate_window(window_days)
    current = clinic_now(now)
    day_start, day_end = _day_bounds(current)
    window_end = day_end + timedelta(days=window_days - 1)

    today_appointments = await _count(
        db,
        Appointment.appointment_time >= day_start,
        Appointment.appointment_time < day_end,
    )
    upcoming_scheduled = await _count(
        db,
        Appointment.status == "scheduled",
        Appointment.appointment_time >= day_start,
        Appointment.appointment_time < window_end,
    )
    upcoming_cancelled = await _count(
        db,
        Appointment.status == "cancelled",
        Appointment.appointment_time >= day_start,
        Appointment.appointment_time < window_end,
    )

    doctor_rows = await db.execute(
        select(
            Doctor.id,
            Doctor.full_name,
            func.count(Appointment.id),
        )
        .join(
            Appointment,
            (Appointment.doctor_id == Doctor.id)
            & (Appointment.status == "scheduled")
            & (Appointment.appointment_time >= day_start)
            & (Appointment.appointment_time < window_end),
            isouter=True,
        )
        .where(Doctor.is_active.is_(True))
        .group_by(Doctor.id, Doctor.full_name)
        .order_by(func.count(Appointment.id).desc(), Doctor.id)
    )
    doctor_load = [
        {
            "doctor_id": int(doctor_id),
            "doctor_name": doctor_name,
            "scheduled_count": int(count or 0),
        }
        for doctor_id, doctor_name, count in doctor_rows.all()
    ]

    return {
        "generated_at": current.isoformat(),
        "window_days": window_days,
        "today_appointments": today_appointments,
        "upcoming_scheduled": upcoming_scheduled,
        "upcoming_cancelled": upcoming_cancelled,
        "doctor_load": doctor_load,
    }


async def clinic_overview_stats(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """Whole-clinic overview for the admin dashboard (all counts are real).

    Record-completeness joins the new ``patients.record_status`` concept so
    the admin can see how many self-service records still miss their
    national id.
    """
    current = clinic_now(now)
    day_start, day_end = _day_bounds(current)

    patients_total = await db.execute(
        select(func.count()).select_from(Patient)
    )
    patients_incomplete = await db.execute(
        select(func.count())
        .select_from(Patient)
        .where(Patient.record_status == "incomplete")
    )
    doctors_total = await db.execute(
        select(func.count())
        .select_from(Doctor)
        .where(Doctor.is_active.is_(True))
    )
    services_total = await db.execute(
        select(func.count())
        .select_from(DentalService)
        .where(DentalService.is_active.is_(True))
    )
    appointments_future = await _count(
        db,
        Appointment.status == "scheduled",
        Appointment.appointment_time >= day_start,
    )
    appointments_today = await _count(
        db,
        Appointment.status == "scheduled",
        Appointment.appointment_time >= day_start,
        Appointment.appointment_time < day_end,
    )
    # Cancellations in the last 30 days: everything cancelled whose slot
    # falls in [today-30d, tomorrow) — past cancellations plus anything
    # cancelled that was booked for today. Future-window lost slots are
    # reported separately as ``upcoming_cancelled``.
    window_start = day_start - timedelta(days=DEFAULT_WINDOW_DAYS)
    cancellations_30d = await _count(
        db,
        Appointment.status == "cancelled",
        Appointment.appointment_time >= window_start,
        Appointment.appointment_time < day_end,
    )

    return {
        "generated_at": current.isoformat(),
        "patients_total": int(patients_total.scalar_one()),
        "patients_incomplete": int(patients_incomplete.scalar_one()),
        "doctors_total": int(doctors_total.scalar_one()),
        "services_total": int(services_total.scalar_one()),
        "appointments_upcoming": appointments_future,
        "appointments_today": appointments_today,
        "cancellations_30d": cancellations_30d,
    }
