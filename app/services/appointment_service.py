"""Appointment domain operations and persistence."""

from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
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
    now: datetime | None = None,
) -> datetime:
    """Validate doctor/service eligibility and return a free future slot."""
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
    # Compare against Tehran wall-clock time in one representation. A slot at
    # the current minute is already in progress, so it is rejected as well.
    if appointment_datetime <= clinic_now(now):
        raise AppError("APPOINTMENT_SLOT_IN_PAST")

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


async def validate_appointment_slot(
    db: AsyncSession,
    doctor_id: int,
    service_id: int,
    appointment_date: str,
    appointment_time: str,
    *,
    exclude_appointment_id: int | None = None,
    now: datetime | None = None,
) -> datetime:
    """Read-only slot validation for confirmations before any write.

    The same rules are enforced again atomically when the write executes, so a
    slot that changes after the prompt is still rejected.
    """
    return await _validate_appointment_slot(
        db,
        doctor_id,
        service_id,
        appointment_date,
        appointment_time,
        exclude_appointment_id=exclude_appointment_id,
        now=now,
    )


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
    now: datetime | None = None,
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
        now=now,
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
    *,
    now: datetime | None = None,
    actor_role: str | None = None,
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
            now=now,
        )
        appointment.appointment_time = new_datetime
        await db.flush()

        # Same-transaction inbox notification (best effort, flush only).
        from app.services import notification_service

        await notification_service.notify_appointment_event(
            db, appointment, event="rescheduled", actor_role=actor_role
        )

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


APPOINTMENT_LIST_LIMIT = 200
_APPOINTMENT_STATUSES = frozenset(
    {"scheduled", "in_progress", "completed", "cancelled", "no_show"}
)
# Statuses that still belong to the active patient journey. The unique slot
# index deliberately guards only ``scheduled``: once a patient is checked in
# the booked minute is in the past and no longer needs reservation.
_ACTIVE_FLOW_STATUSES = frozenset({"scheduled", "in_progress"})


def _appointment_detail(
    row: tuple[Appointment, Patient, Doctor, DentalService],
) -> dict[str, object]:
    """Enrich one joined row with readable names and Jalali date/time."""
    appointment, patient, doctor, service = row
    appointment_date, appointment_time = gregorian_to_jalali(
        appointment.appointment_time
    )
    return {
        "id": appointment.id,
        "patient_id": appointment.patient_id,
        "doctor_id": appointment.doctor_id,
        "service_id": appointment.service_id,
        "appointment_date": appointment_date,
        "appointment_time": appointment_time,
        "status": appointment.status,
        "reason": appointment.reason,
        "patient_name": patient.full_name,
        "doctor_name": doctor.full_name,
        "service_name": service.name,
        "checked_in_at": appointment.checked_in_at,
        "started_at": appointment.started_at,
        "completed_at": appointment.completed_at,
        "queue_number": appointment.queue_number,
    }


async def get_appointments_detail(
    db: AsyncSession,
    *,
    patient_id: int | None = None,
    patient_ids: list[int] | None = None,
    doctor_id: int | None = None,
    appointment_date: str | None = None,
    status: str | None = None,
) -> list[dict[str, object]]:
    """List appointments joined with readable names, newest first.

    Filters are plain equality checks on real database columns; the date
    filter accepts a Jalali day and matches the whole Tehran wall-clock day.
    Caller authorization (role/ownership scoping) happens before this call,
    so this function is presentation-only enrichment. Results are capped to
    keep responses bounded.
    """
    if status is not None and status not in _APPOINTMENT_STATUSES:
        raise AppError("COMMON_VALIDATION_ERROR")

    day_range: tuple[datetime, datetime] | None = None
    if appointment_date is not None:
        try:
            day_start = jalali_to_gregorian(appointment_date, "00:00")
        except ValueError as exc:
            raise AppError("APPOINTMENT_INVALID_DATE") from exc
        day_range = (day_start, day_start + timedelta(days=1))

    query = (
        select(Appointment, Patient, Doctor, DentalService)
        .join(Patient, Appointment.patient_id == Patient.id)
        .join(Doctor, Appointment.doctor_id == Doctor.id)
        .join(DentalService, Appointment.service_id == DentalService.id)
    )
    if patient_id is not None:
        query = query.where(Appointment.patient_id == patient_id)
    if patient_ids is not None:
        query = query.where(Appointment.patient_id.in_(patient_ids))
    if doctor_id is not None:
        query = query.where(Appointment.doctor_id == doctor_id)
    if status is not None:
        query = query.where(Appointment.status == status)
    if day_range is not None:
        query = query.where(
            Appointment.appointment_time >= day_range[0],
            Appointment.appointment_time < day_range[1],
        )
    result = await db.execute(
        query.order_by(
            Appointment.appointment_time.desc(),
            Appointment.id.desc(),
        ).limit(APPOINTMENT_LIST_LIMIT)
    )
    return [_appointment_detail(row) for row in result.all()]


def _day_bounds(target_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(target_date, datetime.min.time())
    return start, start + timedelta(days=1)


async def get_day_worklist(
    db: AsyncSession,
    appointment_date: str,
    *,
    doctor_id: int | None = None,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    """Today's operational worklist in slot-time order.

    Unlike the historical listing this returns the front-desk timestamps plus
    the patient phone, which the reception screen needs without an extra
    request per row. Ordering by queue number is a per-doctor decision made by
    the reception view, because each room counts its own arrivals.
    """
    try:
        day_start = jalali_to_gregorian(appointment_date, "00:00")
    except ValueError as exc:
        raise AppError("APPOINTMENT_INVALID_DATE") from exc
    day_end = day_start + timedelta(days=1)

    query = (
        select(Appointment, Patient, Doctor, DentalService)
        .join(Patient, Appointment.patient_id == Patient.id)
        .join(Doctor, Appointment.doctor_id == Doctor.id)
        .join(DentalService, Appointment.service_id == DentalService.id)
        .where(
            Appointment.appointment_time >= day_start,
            Appointment.appointment_time < day_end,
        )
    )
    if doctor_id is not None:
        query = query.where(Appointment.doctor_id == doctor_id)

    rows = (
        await db.execute(
            query.order_by(
                Appointment.appointment_time.asc(),
                Appointment.id.asc(),
            )
        )
    ).all()

    current = clinic_now(now)
    items: list[dict[str, object]] = []
    for appointment, patient, doctor, service in rows:
        appointment_date_value, appointment_time_value = gregorian_to_jalali(
            appointment.appointment_time
        )
        items.append(
            {
                "id": appointment.id,
                "patient_id": appointment.patient_id,
                "patient_name": patient.full_name,
                "patient_phone": patient.phone,
                "doctor_id": appointment.doctor_id,
                "doctor_name": doctor.full_name,
                "service_id": appointment.service_id,
                "service_name": service.name,
                "appointment_date": appointment_date_value,
                "appointment_time": appointment_time_value,
                "status": appointment.status,
                "reason": appointment.reason,
                "checked_in_at": appointment.checked_in_at,
                "started_at": appointment.started_at,
                "completed_at": appointment.completed_at,
                "queue_number": appointment.queue_number,
                "is_late": appointment.status == "scheduled"
                and appointment.checked_in_at is None
                and appointment.appointment_time < current,
                "waiting_minutes": (
                    max(
                        0,
                        int(
                            (
                                current - appointment.checked_in_at
                            ).total_seconds()
                            // 60
                        ),
                    )
                    if appointment.checked_in_at is not None
                    and appointment.started_at is None
                    and appointment.status == "scheduled"
                    else None
                ),
            }
        )
    return items


async def _load_today_appointment(
    db: AsyncSession,
    appointment_id: int,
    now: datetime | None,
) -> Appointment:
    appointment = await db.get(Appointment, appointment_id)
    if appointment is None:
        raise AppError("APPOINTMENT_NOT_FOUND")
    if appointment.appointment_time.date() != clinic_now(now).date():
        raise AppError("APPOINTMENT_NOT_TODAY")
    return appointment


async def _next_queue_number(
    db: AsyncSession,
    day: date,
    doctor_id: int,
) -> int:
    """Next arrival number for one doctor's room on one day.

    Each doctor runs their own queue, so two rooms never share numbers: a
    patient is "number 2 of Dr. A" and "number 1 of Dr. B" can coexist in the
    same clinic day, which is how rooms are actually called in.
    """
    day_start, day_end = _day_bounds(day)
    current_max = await db.scalar(
        select(func.max(Appointment.queue_number)).where(
            Appointment.appointment_time >= day_start,
            Appointment.appointment_time < day_end,
            Appointment.doctor_id == doctor_id,
        )
    )
    return int(current_max or 0) + 1


async def check_in_appointment(
    db: AsyncSession,
    appointment_id: int,
    *,
    now: datetime | None = None,
) -> Appointment:
    """Register the patient's arrival and assign the doctor's daily queue number."""
    current = clinic_now(now)
    appointment = await _load_today_appointment(db, appointment_id, current)
    if appointment.status in ("cancelled", "completed", "no_show"):
        raise AppError("APPOINTMENT_FLOW_INVALID")
    if appointment.checked_in_at is not None:
        return appointment

    appointment.checked_in_at = current
    if appointment.queue_number is None:
        appointment.queue_number = await _next_queue_number(
            db, current.date(), appointment.doctor_id
        )
    await db.commit()
    await db.refresh(appointment)
    return appointment


async def start_appointment(
    db: AsyncSession,
    appointment_id: int,
    *,
    now: datetime | None = None,
) -> Appointment:
    """Move a checked-in patient into the treatment room."""
    current = clinic_now(now)
    appointment = await _load_today_appointment(db, appointment_id, current)
    if appointment.status not in _ACTIVE_FLOW_STATUSES:
        raise AppError("APPOINTMENT_FLOW_INVALID")
    if appointment.checked_in_at is None:
        # Starting treatment implies the patient is present.
        appointment.checked_in_at = current
        if appointment.queue_number is None:
            appointment.queue_number = await _next_queue_number(
                db, current.date(), appointment.doctor_id
            )
    if appointment.started_at is None:
        appointment.started_at = current
    appointment.status = "in_progress"
    await db.commit()
    await db.refresh(appointment)
    return appointment


async def complete_appointment(
    db: AsyncSession,
    appointment_id: int,
    *,
    now: datetime | None = None,
) -> Appointment:
    """Close the visit after treatment is finished."""
    current = clinic_now(now)
    appointment = await _load_today_appointment(db, appointment_id, current)
    if appointment.status in ("cancelled", "completed", "no_show"):
        raise AppError("APPOINTMENT_FLOW_INVALID")
    if appointment.checked_in_at is None:
        appointment.checked_in_at = current
        if appointment.queue_number is None:
            appointment.queue_number = await _next_queue_number(
                db, current.date(), appointment.doctor_id
            )
    if appointment.started_at is None:
        appointment.started_at = current
    appointment.completed_at = current
    appointment.status = "completed"
    await db.commit()
    await db.refresh(appointment)
    return appointment


async def mark_no_show(
    db: AsyncSession,
    appointment_id: int,
    *,
    now: datetime | None = None,
) -> Appointment:
    """Record that the patient never arrived."""
    current = clinic_now(now)
    appointment = await _load_today_appointment(db, appointment_id, current)
    if appointment.status in ("cancelled", "completed", "no_show"):
        raise AppError("APPOINTMENT_FLOW_INVALID")
    if appointment.checked_in_at is not None:
        raise AppError("APPOINTMENT_FLOW_INVALID")
    appointment.status = "no_show"
    appointment.completed_at = current
    await db.commit()
    await db.refresh(appointment)
    return appointment


async def cancel_appointment(
    db: AsyncSession,
    appointment_id: int,
    *,
    actor_role: str | None = None,
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

    # Same-transaction inbox notification (best effort, flush only).
    from app.services import notification_service

    await notification_service.notify_appointment_event(
        db, appointment, event="cancelled", actor_role=actor_role
    )

    await db.commit()
    await db.refresh(appointment)
    return appointment


async def get_available_slots(
    db: AsyncSession,
    doctor_id: int,
    appointment_date: str,
    *,
    service_id: int | None = None,
    now: datetime | None = None,
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
    current = clinic_now(now)
    return [
        slot.strftime("%H:%M")
        for slot in build_schedule_slots(target_date, schedules)
        if slot > current and slot not in booked_times
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
