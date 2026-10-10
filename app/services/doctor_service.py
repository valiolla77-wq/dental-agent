"""Doctor domain operations and persistence."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.errors import AppError
from app.models.doctor import Doctor
from app.services.dental_service_service import set_doctor_services


async def create_doctor(
    db: AsyncSession,
    full_name: str,
    specialty: str,
    phone: str,
    service_ids: list[int] | None = None,
) -> Doctor:
    new_doctor = Doctor(
        full_name=full_name,
        specialty=specialty,
        phone=phone,
    )
    await set_doctor_services(db, new_doctor, service_ids or [])
    db.add(new_doctor)

    await db.commit()
    await db.refresh(new_doctor)
    return new_doctor


async def update_doctor(
    db: AsyncSession,
    doctor_id: int,
    full_name: str,
    specialty: str,
    phone: str,
    is_active: bool,
    service_ids: list[int],
) -> Doctor:
    result = await db.execute(
        select(Doctor)
        .options(selectinload(Doctor.dental_services))
        .where(Doctor.id == doctor_id)
    )
    doctor = result.scalar_one_or_none()
    if doctor is None:
        raise AppError("DOCTOR_NOT_FOUND")

    await set_doctor_services(db, doctor, service_ids)
    doctor.full_name = full_name
    doctor.specialty = specialty
    doctor.phone = phone
    doctor.is_active = is_active
    await db.commit()
    await db.refresh(doctor)
    return doctor
