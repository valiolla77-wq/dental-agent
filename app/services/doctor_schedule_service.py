"""Doctor schedule domain operations and persistence."""

from datetime import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.models.doctor import Doctor
from app.models.doctor_schedule import DoctorSchedule


async def create_doctor_schedule(
    db: AsyncSession,
    doctor_id: int,
    day_of_week: int,
    start_time: time,
    end_time: time,
    slot_duration_minutes: int,
) -> DoctorSchedule:
    doctor = await db.get(Doctor, doctor_id)
    if doctor is None:
        raise AppError("DOCTOR_NOT_FOUND")

    new_schedule = DoctorSchedule(
        doctor_id=doctor_id,
        day_of_week=day_of_week,
        start_time=start_time,
        end_time=end_time,
        slot_duration_minutes=slot_duration_minutes,
    )
    db.add(new_schedule)

    await db.commit()
    await db.refresh(new_schedule)
    return new_schedule


async def list_doctor_schedules(
    db: AsyncSession,
    doctor_id: int,
) -> list[DoctorSchedule]:
    result = await db.execute(
        select(DoctorSchedule)
        .where(DoctorSchedule.doctor_id == doctor_id)
        .order_by(DoctorSchedule.day_of_week)
    )
    return list(result.scalars().all())


async def _get_schedule(
    db: AsyncSession,
    schedule_id: int,
) -> DoctorSchedule:
    schedule = await db.get(DoctorSchedule, schedule_id)
    if schedule is None:
        raise AppError("DOCTOR_SCHEDULE_NOT_FOUND")
    return schedule


async def update_doctor_schedule(
    db: AsyncSession,
    schedule_id: int,
    day_of_week: int,
    start_time: time,
    end_time: time,
    slot_duration_minutes: int,
    is_active: bool,
) -> DoctorSchedule:
    schedule = await _get_schedule(db, schedule_id)
    schedule.day_of_week = day_of_week
    schedule.start_time = start_time
    schedule.end_time = end_time
    schedule.slot_duration_minutes = slot_duration_minutes
    schedule.is_active = is_active

    await db.commit()
    await db.refresh(schedule)
    return schedule


async def delete_doctor_schedule(
    db: AsyncSession,
    schedule_id: int,
) -> int:
    schedule = await _get_schedule(db, schedule_id)
    await db.delete(schedule)
    await db.commit()
    return schedule_id
