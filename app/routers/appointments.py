from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.appointment import Appointment
from app.models.clinic_setting import ClinicSetting
from app.models.doctor import Doctor
from app.models.doctor_schedule import DoctorSchedule
from app.models.patient import Patient
from app.schemas.appointment import (
    AppointmentCreate,
    AppointmentResponse,
)
from app.utils.date_utils import (
    gregorian_to_jalali,
    jalali_to_gregorian,
)
from app.errors import AppError


router = APIRouter(
    prefix="/appointments",
    tags=["Appointments"],
)


def build_schedule_slots(
    target_date: date,
    schedules: list[DoctorSchedule],
) -> list[datetime]:
    """
    ساخت تمام Slotهای معتبر یک روز بر اساس برنامه کاری پزشک.
    """

    slots: set[datetime] = set()

    for schedule in schedules:
        current_time = datetime.combine(
            target_date,
            schedule.start_time,
        )

        schedule_end = datetime.combine(
            target_date,
            schedule.end_time,
        )

        while current_time < schedule_end:
            slots.add(current_time)

            current_time += timedelta(
                minutes=schedule.slot_duration_minutes
            )

    return sorted(slots)


async def get_doctor_schedules_for_date(
    doctor_id: int,
    appointment_datetime: datetime,
    db: AsyncSession,
) -> list[DoctorSchedule]:
    """
    دریافت برنامه کاری فعال پزشک برای روز موردنظر.
    """

    day_of_week = (
        appointment_datetime.weekday() + 1
    ) % 7

    result = await db.execute(
        select(DoctorSchedule).where(
            DoctorSchedule.doctor_id == doctor_id,
            DoctorSchedule.day_of_week == day_of_week,
            DoctorSchedule.is_active.is_(True),
        )
    )

    return list(result.scalars().all())


async def get_clinic_settings(
    db: AsyncSession,
) -> ClinicSetting:
    """
    دریافت تنظیمات مطب.
    اگر تنظیمات وجود نداشته باشد، تنظیمات پیش‌فرض ساخته می‌شود.
    """

    settings = await db.get(
        ClinicSetting,
        1,
    )

    if settings is None:
        settings = ClinicSetting(
            id=1,
            max_appointments_per_day=0,
            max_appointments_per_week=0,
            max_appointments_per_month=0,
        )

        db.add(settings)

        await db.commit()
        await db.refresh(settings)

    return settings


def get_week_start(
    target_date: date,
) -> date:
    """
    شروع هفته بر اساس تقویم میلادی.
    Monday به عنوان شروع هفته در نظر گرفته می‌شود.
    """

    return target_date - timedelta(
        days=target_date.weekday()
    )


def get_month_range(
    target_date: date,
) -> tuple[date, date]:
    """
    دریافت شروع و پایان ماه میلادی.
    """

    month_start = target_date.replace(
        day=1,
    )

    if target_date.month == 12:
        next_month = date(
            target_date.year + 1,
            1,
            1,
        )
    else:
        next_month = date(
            target_date.year,
            target_date.month + 1,
            1,
        )

    return month_start, next_month


async def check_patient_appointment_limits(
    patient_id: int,
    appointment_datetime: datetime,
    settings: ClinicSetting,
    db: AsyncSession,
) -> None:
    """
    بررسی محدودیت تعداد نوبت‌های فعال بیمار
    در روز، هفته و ماه.
    """

    target_date = appointment_datetime.date()

    # ---------------------------------
    # محدودیت روزانه
    # ---------------------------------

    if settings.max_appointments_per_day > 0:
        day_start = datetime.combine(
            target_date,
            datetime.min.time(),
        )

        day_end = day_start + timedelta(
            days=1,
        )

        result = await db.execute(
            select(func.count(Appointment.id)).where(
                Appointment.patient_id == patient_id,
                Appointment.appointment_time >= day_start,
                Appointment.appointment_time < day_end,
                Appointment.status == "scheduled",
            )
        )

        daily_count = result.scalar_one()

        if (
            daily_count
            >= settings.max_appointments_per_day
        ):
            raise AppError("APPOINTMENT_DAILY_LIMIT", {
                "limit": settings.max_appointments_per_day,
                "current_count": daily_count,
            })

    # ---------------------------------
    # محدودیت هفتگی
    # ---------------------------------

    if settings.max_appointments_per_week > 0:
        week_start_date = get_week_start(
            target_date,
        )

        week_end_date = week_start_date + timedelta(
            days=7,
        )

        week_start = datetime.combine(
            week_start_date,
            datetime.min.time(),
        )

        week_end = datetime.combine(
            week_end_date,
            datetime.min.time(),
        )

        result = await db.execute(
            select(func.count(Appointment.id)).where(
                Appointment.patient_id == patient_id,
                Appointment.appointment_time >= week_start,
                Appointment.appointment_time < week_end,
                Appointment.status == "scheduled",
            )
        )

        weekly_count = result.scalar_one()

        if (
            weekly_count
            >= settings.max_appointments_per_week
        ):
            raise AppError("APPOINTMENT_WEEKLY_LIMIT", {
                "limit": settings.max_appointments_per_week,
                "current_count": weekly_count,
            })

    # ---------------------------------
    # محدودیت ماهانه
    # ---------------------------------

    if settings.max_appointments_per_month > 0:
        month_start_date, next_month_date = (
            get_month_range(target_date)
        )

        month_start = datetime.combine(
            month_start_date,
            datetime.min.time(),
        )

        month_end = datetime.combine(
            next_month_date,
            datetime.min.time(),
        )

        result = await db.execute(
            select(func.count(Appointment.id)).where(
                Appointment.patient_id == patient_id,
                Appointment.appointment_time >= month_start,
                Appointment.appointment_time < month_end,
                Appointment.status == "scheduled",
            )
        )

        monthly_count = result.scalar_one()

        if (
            monthly_count
            >= settings.max_appointments_per_month
        ):
            raise AppError("APPOINTMENT_MONTHLY_LIMIT", {
                "limit": settings.max_appointments_per_month,
                "current_count": monthly_count,
            })


@router.post(
    "/",
    response_model=AppointmentResponse,
)
async def create_appointment(
    appointment: AppointmentCreate,
    db: AsyncSession = Depends(get_db),
):
    # ---------------------------------
    # بررسی بیمار
    # ---------------------------------

    patient = await db.get(
        Patient,
        appointment.patient_id,
    )

    if patient is None:
        raise AppError("PATIENT_NOT_FOUND")

    # ---------------------------------
    # بررسی پزشک
    # ---------------------------------

    doctor = await db.get(
        Doctor,
        appointment.doctor_id,
    )

    if doctor is None:
        raise AppError("DOCTOR_NOT_FOUND")

    if not doctor.is_active:
        raise AppError("DOCTOR_INACTIVE")

    # ---------------------------------
    # تبدیل تاریخ و ساعت
    # ---------------------------------

    try:
        appointment_datetime = jalali_to_gregorian(
            appointment.appointment_date,
            appointment.appointment_time,
        )
    except ValueError:
        raise AppError("APPOINTMENT_INVALID_DATE_OR_TIME")

    # ---------------------------------
    # بررسی برنامه کاری پزشک
    # ---------------------------------

    schedules = await get_doctor_schedules_for_date(
        appointment.doctor_id,
        appointment_datetime,
        db,
    )

    if not schedules:
        raise AppError("APPOINTMENT_DOCTOR_NOT_SCHEDULED")

    # ---------------------------------
    # ساخت Slotهای معتبر
    # ---------------------------------

    valid_slots = build_schedule_slots(
        appointment_datetime.date(),
        schedules,
    )

    if appointment_datetime not in valid_slots:
        raise AppError("APPOINTMENT_SLOT_INVALID")

    # ---------------------------------
    # بررسی اشغال بودن Slot
    # ---------------------------------

    result = await db.execute(
        select(Appointment).where(
            Appointment.doctor_id == appointment.doctor_id,
            Appointment.appointment_time == appointment_datetime,
            Appointment.status == "scheduled",
        )
    )

    existing_appointment = result.scalar_one_or_none()

    if existing_appointment:
        raise AppError("APPOINTMENT_SLOT_BOOKED")

    # ---------------------------------
    # دریافت تنظیمات مطب
    # ---------------------------------

    settings = await get_clinic_settings(
        db,
    )

    # ---------------------------------
    # بررسی محدودیت‌های بیمار
    # ---------------------------------

    await check_patient_appointment_limits(
        patient_id=appointment.patient_id,
        appointment_datetime=appointment_datetime,
        settings=settings,
        db=db,
    )

    # ---------------------------------
    # ایجاد نوبت
    # ---------------------------------

    new_appointment = Appointment(
        patient_id=appointment.patient_id,
        doctor_id=appointment.doctor_id,
        appointment_time=appointment_datetime,
        status="scheduled",
        reason=appointment.reason,
    )

    db.add(new_appointment)

    await db.commit()
    await db.refresh(new_appointment)

    # ---------------------------------
    # تبدیل پاسخ به تاریخ و ساعت شمسی
    # ---------------------------------

    jalali_date, jalali_time = gregorian_to_jalali(
        new_appointment.appointment_time
    )

    return {
        "id": new_appointment.id,
        "patient_id": new_appointment.patient_id,
        "doctor_id": new_appointment.doctor_id,
        "appointment_date": jalali_date,
        "appointment_time": jalali_time,
        "status": new_appointment.status,
        "reason": new_appointment.reason,
    }


@router.get(
    "/patient/{patient_id}",
    response_model=list[AppointmentResponse],
)
async def get_patient_appointments(
    patient_id: int,
    db: AsyncSession = Depends(get_db),
):
    # بررسی وجود بیمار
    patient = await db.get(
        Patient,
        patient_id,
    )

    if patient is None:
        raise AppError("PATIENT_NOT_FOUND")

    result = await db.execute(
        select(Appointment)
        .where(
            Appointment.patient_id == patient_id,
        )
        .order_by(
            Appointment.appointment_time,
        )
    )

    appointments = result.scalars().all()

    response = []

    for appointment in appointments:
        jalali_date, jalali_time = gregorian_to_jalali(
            appointment.appointment_time
        )

        response.append(
            {
                "id": appointment.id,
                "patient_id": appointment.patient_id,
                "doctor_id": appointment.doctor_id,
                "appointment_date": jalali_date,
                "appointment_time": jalali_time,
                "status": appointment.status,
                "reason": appointment.reason,
            }
        )

    return response


@router.get("/available-slots/")
async def get_available_slots(
    doctor_id: int,
    appointment_date: str,
    db: AsyncSession = Depends(get_db),
):
    # بررسی پزشک
    doctor = await db.get(
        Doctor,
        doctor_id,
    )

    if doctor is None:
        raise AppError("DOCTOR_NOT_FOUND")

    if not doctor.is_active:
        raise AppError("DOCTOR_INACTIVE")

    # تبدیل تاریخ شمسی به میلادی
    try:
        appointment_datetime = jalali_to_gregorian(
            appointment_date,
            "00:00",
        )
    except ValueError:
        raise AppError("APPOINTMENT_INVALID_DATE")

    # پیدا کردن برنامه کاری پزشک
    schedules = await get_doctor_schedules_for_date(
        doctor_id,
        appointment_datetime,
        db,
    )

    if not schedules:
        return {
            "doctor_id": doctor_id,
            "date": appointment_date,
            "available_slots": [],
        }

    # ساخت همه Slotهای معتبر
    all_slots = build_schedule_slots(
        appointment_datetime.date(),
        schedules,
    )

    # محدوده روز
    day_start = appointment_datetime.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    day_end = day_start + timedelta(
        days=1,
    )

    # دریافت نوبت‌های رزروشده آن روز
    result = await db.execute(
        select(Appointment).where(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_time >= day_start,
            Appointment.appointment_time < day_end,
            Appointment.status == "scheduled",
        )
    )

    booked_appointments = result.scalars().all()

    booked_times = {
        appointment.appointment_time
        for appointment in booked_appointments
    }

    # حذف Slotهای رزروشده
    available_slots = [
        slot.strftime("%H:%M")
        for slot in all_slots
        if slot not in booked_times
    ]

    return {
        "doctor_id": doctor_id,
        "date": appointment_date,
        "available_slots": available_slots,
    }
