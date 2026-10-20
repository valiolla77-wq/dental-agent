"""Appointment domain operations and persistence."""

from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.models.appointment import APPOINTMENT_SLOT_INDEX, Appointment
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.doctor_dental_service import doctor_dental_services
from app.models.doctor_schedule import DoctorSchedule
from app.models.patient import Patient
from app.utils.date_utils import gregorian_to_jalali, jalali_to_gregorian

CLINIC_TIMEZONE = ZoneInfo("Asia/Tehran")


def _is_appointment_slot_conflict(exc: IntegrityError) -> bool:
    """Distinguish our partial unique slot index from unrelated DB errors."""
    message = str(getattr(exc, "orig", exc))
    if APPOINTMENT_SLOT_INDEX in message:
        return True
    return (
        "UNIQUE constraint failed" in message
        and "appointments.doctor_id" in message
        and "appointments.appointment_time" in message
    )


def saturday_based_day_of_week(target_date: date) -> int:
    """Return Saturday=0 through Friday=6 for a Gregorian date."""
    return (target_date.weekday() + 2) % 7


def build_schedule_slots(
    target_date: date,
    schedules: list[DoctorSchedule],
) -> list[datetime]:
    """Build start times inside each schedule; duration is the start interval."""
    slots: set[datetime] = set()

    for schedule in schedules:
        if schedule.slot_duration_minutes <= 0:
            continue

        current_time = datetime.combine(target_date, schedule.start_time)
        schedule_end = datetime.combine(target_date, schedule.end_time)
        while current_time < schedule_end:
            slots.add(current_time)
            current_time += timedelta(minutes=schedule.slot_duration_minutes)

    return sorted(slots)


async def get_doctor_schedules_for_date(
    db: AsyncSession,
    doctor_id: int,
    target_date: date,
) -> list[DoctorSchedule]:
    day_of_week = saturday_based_day_of_week(target_date)
    result = await db.execute(
        select(DoctorSchedule).where(
            DoctorSchedule.doctor_id == doctor_id,
            DoctorSchedule.day_of_week == day_of_week,
            DoctorSchedule.is_active.is_(True),
        )
    )
    return list(result.scalars().all())


async def _get_active_doctor(db: AsyncSession, doctor_id: int) -> Doctor:
    doctor = await db.get(Doctor, doctor_id)
    if doctor is None:
        raise AppError("DOCTOR_NOT_FOUND")
    if not doctor.is_active:
        raise AppError("DOCTOR_INACTIVE")
    return doctor


def _parse_appointment_datetime(
    appointment_date: str,
    appointment_time: str,
) -> datetime:
    try:
        return jalali_to_gregorian(appointment_date, appointment_time)
    except ValueError as exc:
        raise AppError("APPOINTMENT_INVALID_DATE_OR_TIME") from exc


async def _validate_appointment_slot(
    db: AsyncSession,
    doctor_id: int,
    service_id: int,
    appointment_date: str,
    appointment_time: str,
    *,
    exclude_appointment_id: int | None = None,
) -> datetime:
    """Validate doctor/service eligibility and return a free valid slot."""
    doctor = await _get_active_doctor(db, doctor_id)
    dental_service = await db.get(DentalService, service_id)
    if dental_service is None:
        raise AppError("DENTAL_SERVICE_NOT_FOUND")
    if not dental_service.is_active:
        raise AppError("APPOINTMENT_SERVICE_INACTIVE")

    offers_service = await db.scalar(
        select(doctor_dental_services.c.doctor_id).where(
            doctor_dental_services.c.doctor_id == doctor.id,
            doctor_dental_services.c.dental_service_id == service_id,
        )
    )
    if offers_service is None:
        raise AppError("APPOINTMENT_DOCTOR_SERVICE_MISMATCH")

    appointment_datetime = _parse_appointment_datetime(
        appointment_date,
        appointment_time,
    )
    schedules = await get_doctor_schedules_for_date(
        db, doctor_id, appointment_datetime.date()
    )
    if not schedules:
        raise AppError("APPOINTMENT_DOCTOR_NOT_SCHEDULED")
    if appointment_datetime not in build_schedule_slots(
        appointment_datetime.date(), schedules
    ):
        raise AppError("APPOINTMENT_SLOT_INVALID")

    conflict_query = select(Appointment.id).where(
        Appointment.doctor_id == doctor_id,
        Appointment.appointment_time == appointment_datetime,
        Appointment.status == "scheduled",
    )
    if exclude_appointment_id is not None:
        conflict_query = conflict_query.where(
            Appointment.id != exclude_appointment_id
        )
    existing = await db.execute(conflict_query)
    if existing.scalar_one_or_none() is not None:
        raise AppError("APPOINTMENT_SLOT_BOOKED")
    return appointment_datetime


async def create_appointment(
    db: AsyncSession,
    patient_id: int,
    doctor_id: int,
    service_id: int,
    appointment_date: str,
    appointment_time: str,
    reason: str | None = None,
    *,
    commit: bool = True,
) -> Appointment:
    patient = await db.get(Patient, patient_id)
    if patient is None:
        raise AppError("PATIENT_NOT_FOUND")

    appointment_datetime = await _validate_appointment_slot(
        db,
        doctor_id,
        service_id,
        appointment_date,
        appointment_time,
    )

    appointment = Appointment(
        patient_id=patient_id,
        doctor_id=doctor_id,
        service_id=service_id,
        appointment_time=appointment_datetime,
        status="scheduled",
        reason=reason,
    )
    db.add(appointment)
    try:
        if commit:
            await db.commit()
            await db.refresh(appointment)
        else:
            await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if _is_appointment_slot_conflict(exc):
            raise AppError("APPOINTMENT_SLOT_BOOKED") from exc
        raise
    return appointment


async def reschedule_appointment(
    db: AsyncSession,
    appointment_id: int,
    appointment_date: str,
    appointment_time: str,
) -> Appointment:
    """Move a scheduled appointment atomically without creating history.

    This service owns the session's transaction boundary: it commits once on
    success and rolls back on any failure, whether the caller's session is
    fresh or already has a read transaction open from an authorization check.
    """
    try:
        appointment = await db.get(Appointment, appointment_id)
        if appointment is None:
            raise AppError("APPOINTMENT_NOT_FOUND")
        if appointment.status == "cancelled":
            raise AppError("APPOINTMENT_ALREADY_CANCELLED")
        if appointment.status != "scheduled":
            raise AppError("APPOINTMENT_NOT_RESCHEDULABLE")

        new_datetime = await _validate_appointment_slot(
            db,
            appointment.doctor_id,
            appointment.service_id,
            appointment_date,
            appointment_time,
            exclude_appointment_id=appointment.id,
        )
        appointment.appointment_time = new_datetime
        await db.flush()
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if _is_appointment_slot_conflict(exc):
            raise AppError("APPOINTMENT_SLOT_BOOKED") from exc
        raise
    except Exception:
        await db.rollback()
        raise

    await db.refresh(appointment)
    return appointment


async def get_patient_appointments(
    db: AsyncSession,
    patient_id: int,
) -> list[Appointment]:
    patient = await db.get(Patient, patient_id)
    if patient is None:
        raise AppError("PATIENT_NOT_FOUND")

    result = await db.execute(
        select(Appointment)
        .where(Appointment.patient_id == patient_id)
        .order_by(Appointment.appointment_time)
    )
    return list(result.scalars().all())


async def cancel_appointment(
    db: AsyncSession,
    appointment_id: int,
) -> Appointment:
    """Cancel a scheduled appointment and reject every other state."""
    appointment = await db.get(Appointment, appointment_id)
    if appointment is None:
        raise AppError("APPOINTMENT_NOT_FOUND")
    if appointment.status == "cancelled":
        raise AppError("APPOINTMENT_ALREADY_CANCELLED")
    if appointment.status != "scheduled":
        raise AppError("APPOINTMENT_NOT_CANCELLABLE")

    appointment.status = "cancelled"
    await db.commit()
    await db.refresh(appointment)
    return appointment


async def get_available_slots(
    db: AsyncSession,
    doctor_id: int,
    appointment_date: str,
    *,
    service_id: int | None = None,
) -> list[str]:
    doctor = await _get_active_doctor(db, doctor_id)
    if service_id is not None:
        dental_service = await db.get(DentalService, service_id)
        if dental_service is None:
            raise AppError("DENTAL_SERVICE_NOT_FOUND")
        if not dental_service.is_active:
            raise AppError("APPOINTMENT_SERVICE_INACTIVE")

        offers_service = await db.scalar(
            select(doctor_dental_services.c.doctor_id).where(
                doctor_dental_services.c.doctor_id == doctor.id,
                doctor_dental_services.c.dental_service_id == service_id,
            )
        )
        if offers_service is None:
            raise AppError("APPOINTMENT_DOCTOR_SERVICE_MISMATCH")

    try:
        target_datetime = jalali_to_gregorian(appointment_date, "00:00")
    except ValueError as exc:
        raise AppError("APPOINTMENT_INVALID_DATE") from exc

    target_date = target_datetime.date()
    schedules = await get_doctor_schedules_for_date(db, doctor_id, target_date)
    if not schedules:
        return []

    day_start = datetime.combine(target_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    result = await db.execute(
        select(Appointment.appointment_time).where(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_time >= day_start,
            Appointment.appointment_time < day_end,
            Appointment.status == "scheduled",
        )
    )
    booked_times = set(result.scalars().all())
    return [
        slot.strftime("%H:%M")
        for slot in build_schedule_slots(target_date, schedules)
        if slot not in booked_times
    ]


def clinic_now(now: datetime | None = None) -> datetime:
    """Return a naive Asia/Tehran wall-clock time for slot comparisons."""
    if now is None:
        current = datetime.now(CLINIC_TIMEZONE)
    elif now.tzinfo is None:
        current = now.replace(tzinfo=CLINIC_TIMEZONE)
    else:
        current = now.astimezone(CLINIC_TIMEZONE)
    return current.replace(tzinfo=None)


async def find_nearest_available_slots(
    db: AsyncSession,
    *,
    service_id: int | None = None,
    doctor_id: int | None = None,
    days: int = 30,
    limit: int = 3,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    """Find the earliest real free slots across a forward date range.

    Appointments use the doctor's fixed, non-overlapping schedule slots.
    Past slots and ``scheduled`` appointments are excluded. If the service or
    doctor is omitted, all active eligible pairs are searched. Results are
    sorted by time and capped at ``limit``.
    """
    days = max(1, min(int(days), 60))
    limit = max(1, min(int(limit), 10))
    current = clinic_now(now)
    start_date = current.date()
    range_end = datetime.combine(
        start_date + timedelta(days=days), datetime.min.time()
    )

    services: dict[int, DentalService] = {}
    if service_id is not None:
        service = await db.get(DentalService, service_id)
        if service is None:
            raise AppError("DENTAL_SERVICE_NOT_FOUND")
        if not service.is_active:
            raise AppError("APPOINTMENT_SERVICE_INACTIVE")
        services[service.id] = service
    else:
        result = await db.execute(
            select(DentalService).where(DentalService.is_active.is_(True))
        )
        services = {item.id: item for item in result.scalars().all()}
    if not services:
        return []

    doctors: dict[int, Doctor] = {}
    if doctor_id is not None:
        doctor = await db.get(Doctor, doctor_id)
        if doctor is None:
            raise AppError("DOCTOR_NOT_FOUND")
        if not doctor.is_active:
            raise AppError("DOCTOR_INACTIVE")
        doctors[doctor.id] = doctor
    else:
        result = await db.execute(
            select(Doctor).where(Doctor.is_active.is_(True))
        )
        doctors = {item.id: item for item in result.scalars().all()}
    if not doctors:
        return []

    links = (
        await db.execute(
            select(
                doctor_dental_services.c.doctor_id,
                doctor_dental_services.c.dental_service_id,
            ).where(
                doctor_dental_services.c.doctor_id.in_(doctors),
                doctor_dental_services.c.dental_service_id.in_(services),
            )
        )
    ).all()
    pairs = sorted(
        (row.doctor_id, row.dental_service_id) for row in links
    )
    if not pairs:
        if service_id is not None and doctor_id is not None:
            raise AppError("APPOINTMENT_DOCTOR_SERVICE_MISMATCH")
        return []

    schedules_by_doctor_day: dict[tuple[int, int], list[DoctorSchedule]] = (
        defaultdict(list)
    )
    schedule_rows = (
        await db.execute(
            select(DoctorSchedule).where(
                DoctorSchedule.doctor_id.in_(doctors),
                DoctorSchedule.is_active.is_(True),
            )
        )
    ).scalars().all()
    for schedule in schedule_rows:
        schedules_by_doctor_day[
            (schedule.doctor_id, schedule.day_of_week)
        ].append(schedule)

    booked_rows = (
        await db.execute(
            select(Appointment.doctor_id, Appointment.appointment_time).where(
                Appointment.doctor_id.in_(doctors),
                Appointment.appointment_time
                >= datetime.combine(start_date, datetime.min.time()),
                Appointment.appointment_time < range_end,
                Appointment.status == "scheduled",
            )
        )
    ).all()
    booked = {(row.doctor_id, row.appointment_time) for row in booked_rows}

    candidates: list[tuple[datetime, int, int]] = []
    seen_doctor_slots: set[tuple[int, datetime]] = set()
    for pair_doctor_id, pair_service_id in pairs:
        for offset in range(days):
            target_date = start_date + timedelta(days=offset)
            day_of_week = saturday_based_day_of_week(target_date)
            schedules = schedules_by_doctor_day.get(
                (pair_doctor_id, day_of_week), []
            )
            if not schedules:
                continue
            for slot in build_schedule_slots(target_date, schedules):
                if slot <= current:
                    continue
                if (pair_doctor_id, slot) in booked:
                    continue
                # One doctor/time option is enough; do not show the same
                # start time once per service the doctor offers.
                if (pair_doctor_id, slot) in seen_doctor_slots:
                    continue
                seen_doctor_slots.add((pair_doctor_id, slot))
                candidates.append((slot, pair_doctor_id, pair_service_id))

    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    results: list[dict[str, object]] = []
    for slot, pair_doctor_id, pair_service_id in candidates[:limit]:
        appointment_date, appointment_time = gregorian_to_jalali(slot)
        results.append(
            {
                "doctor_id": pair_doctor_id,
                "doctor_name": doctors[pair_doctor_id].full_name,
                "service_id": pair_service_id,
                "service_name": services[pair_service_id].name,
                "appointment_date": appointment_date,
                "appointment_time": appointment_time,
            }
        )
    return results
