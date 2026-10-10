from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.doctor_schedule import (
    DoctorScheduleCreate,
    DoctorScheduleResponse,
    DoctorScheduleUpdate,
)
from app.services import doctor_schedule_service

router = APIRouter(
    prefix="/doctor-schedules",
    tags=["Doctor Schedules"],
)


@router.post("/", response_model=DoctorScheduleResponse)
async def create_doctor_schedule(
    schedule: DoctorScheduleCreate,
    db: AsyncSession = Depends(get_db),
):
    new_schedule = await doctor_schedule_service.create_doctor_schedule(
        db=db,
        doctor_id=schedule.doctor_id,
        day_of_week=schedule.day_of_week,
        start_time=schedule.start_time,
        end_time=schedule.end_time,
        slot_duration_minutes=schedule.slot_duration_minutes,
    )
    return DoctorScheduleResponse.model_validate(new_schedule)

@router.get("/{doctor_id}", response_model=list[DoctorScheduleResponse])
async def get_doctor_schedules(
    doctor_id: int,
    db: AsyncSession = Depends(get_db),
):
    schedules = await doctor_schedule_service.list_doctor_schedules(
        db,
        doctor_id,
    )
    return [
        DoctorScheduleResponse.model_validate(schedule)
        for schedule in schedules
    ]

@router.put("/{schedule_id}", response_model=DoctorScheduleResponse)
async def update_doctor_schedule(
    schedule_id: int,
    schedule_data: DoctorScheduleUpdate,
    db: AsyncSession = Depends(get_db),
):
    schedule = await doctor_schedule_service.update_doctor_schedule(
        db=db,
        schedule_id=schedule_id,
        day_of_week=schedule_data.day_of_week,
        start_time=schedule_data.start_time,
        end_time=schedule_data.end_time,
        slot_duration_minutes=schedule_data.slot_duration_minutes,
        is_active=schedule_data.is_active,
    )
    return DoctorScheduleResponse.model_validate(schedule)

@router.delete("/{schedule_id}")
async def delete_doctor_schedule(
    schedule_id: int,
    db: AsyncSession = Depends(get_db),
):
    deleted_schedule_id = await doctor_schedule_service.delete_doctor_schedule(
        db,
        schedule_id,
    )

    return {
        "message": "برنامه پزشک با موفقیت حذف شد.",
        "schedule_id": deleted_schedule_id,
    }
