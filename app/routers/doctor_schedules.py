from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.doctor import Doctor
from app.models.doctor_schedule import DoctorSchedule
from app.schemas.doctor_schedule import (
    DoctorScheduleCreate,
    DoctorScheduleResponse,
)
from app.errors import AppError
from sqlalchemy import select
from app.schemas.doctor_schedule import (
    DoctorScheduleCreate,
    DoctorScheduleResponse,
    DoctorScheduleUpdate,
)

router = APIRouter(
    prefix="/doctor-schedules",
    tags=["Doctor Schedules"],
)


@router.post("/", response_model=DoctorScheduleResponse)
async def create_doctor_schedule(
    schedule: DoctorScheduleCreate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.get(Doctor, schedule.doctor_id)

    if result is None:
        raise AppError("DOCTOR_NOT_FOUND")

    new_schedule = DoctorSchedule(
        doctor_id=schedule.doctor_id,
        day_of_week=schedule.day_of_week,
        start_time=schedule.start_time,
        end_time=schedule.end_time,
        slot_duration_minutes=schedule.slot_duration_minutes,
    )

    db.add(new_schedule)

    await db.commit()
    await db.refresh(new_schedule)

    return new_schedule

@router.get("/{doctor_id}", response_model=list[DoctorScheduleResponse])
async def get_doctor_schedules(
    doctor_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DoctorSchedule)
        .where(DoctorSchedule.doctor_id == doctor_id)
        .order_by(DoctorSchedule.day_of_week)
    )

    schedules = result.scalars().all()

    return schedules

@router.put("/{schedule_id}", response_model=DoctorScheduleResponse)
async def update_doctor_schedule(
    schedule_id: int,
    schedule_data: DoctorScheduleUpdate,
    db: AsyncSession = Depends(get_db),
):
    schedule = await db.get(DoctorSchedule, schedule_id)

    if schedule is None:
        raise AppError("DOCTOR_SCHEDULE_NOT_FOUND")

    schedule.day_of_week = schedule_data.day_of_week
    schedule.start_time = schedule_data.start_time
    schedule.end_time = schedule_data.end_time
    schedule.slot_duration_minutes = schedule_data.slot_duration_minutes
    schedule.is_active = schedule_data.is_active

    await db.commit()
    await db.refresh(schedule)

    return schedule

@router.delete("/{schedule_id}")
async def delete_doctor_schedule(
    schedule_id: int,
    db: AsyncSession = Depends(get_db),
):
    schedule = await db.get(DoctorSchedule, schedule_id)

    if schedule is None:
        raise AppError("DOCTOR_SCHEDULE_NOT_FOUND")

    await db.delete(schedule)
    await db.commit()

    return {
        "message": "برنامه پزشک با موفقیت حذف شد.",
        "schedule_id": schedule_id,
    }
