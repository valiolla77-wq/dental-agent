"""Dental service domain operations and persistence."""

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.models.appointment import Appointment
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.doctor_dental_service import doctor_dental_services


async def create_dental_service(
    db: AsyncSession,
    name: str,
    description: str | None = None,
) -> DentalService:
    dental_service = DentalService(name=name, description=description)
    db.add(dental_service)
    await db.commit()
    await db.refresh(dental_service)
    return dental_service


async def list_dental_services(
    db: AsyncSession,
    active_only: bool = True,
) -> list[DentalService]:
    query = select(DentalService)
    if active_only:
        query = query.where(DentalService.is_active.is_(True))
    result = await db.execute(
        query.order_by(DentalService.id)
    )
    return list(result.scalars().all())


async def search_dental_services(
    db: AsyncSession,
    name_query: str | None = None,
) -> list[DentalService]:
    """Return active bookable services matching a name or description.

    A description match lets the agent map a patient's wording (for example
    "پوسیدگی") to an existing service without inventing a service name.
    """
    query = select(DentalService).where(DentalService.is_active.is_(True))
    normalized_query = name_query.strip() if name_query else ""
    if normalized_query:
        pattern = f"%{normalized_query}%"
        query = query.where(
            or_(
                DentalService.name.ilike(pattern),
                DentalService.description.ilike(pattern),
            )
        )
    result = await db.execute(query.order_by(DentalService.id))
    return list(result.scalars().all())


async def get_dental_service(
    db: AsyncSession,
    service_id: int,
) -> DentalService:
    dental_service = await db.get(DentalService, service_id)
    if dental_service is None:
        raise AppError("DENTAL_SERVICE_NOT_FOUND")
    return dental_service


async def update_dental_service(
    db: AsyncSession,
    service_id: int,
    name: str,
    description: str | None,
    is_active: bool,
) -> DentalService:
    dental_service = await get_dental_service(db, service_id)
    dental_service.name = name
    dental_service.description = description
    dental_service.is_active = is_active
    await db.commit()
    await db.refresh(dental_service)
    return dental_service


async def delete_dental_service(db: AsyncSession, service_id: int) -> int:
    dental_service = await get_dental_service(db, service_id)
    appointment_count = await db.scalar(
        select(func.count(Appointment.id)).where(
            Appointment.service_id == service_id
        )
    )
    if appointment_count:
        raise AppError("DENTAL_SERVICE_IN_USE")

    await db.delete(dental_service)
    await db.commit()
    return service_id


async def get_doctor_services(
    db: AsyncSession,
    doctor_id: int,
) -> list[DentalService]:
    doctor = await db.get(Doctor, doctor_id)
    if doctor is None:
        raise AppError("DOCTOR_NOT_FOUND")

    result = await db.execute(
        select(DentalService)
        .join(doctor_dental_services)
        .where(doctor_dental_services.c.doctor_id == doctor_id)
        .order_by(DentalService.id)
    )
    return list(result.scalars().all())


async def get_service_doctors(
    db: AsyncSession,
    service_id: int,
) -> list[Doctor]:
    dental_service = await get_dental_service(db, service_id)
    if not dental_service.is_active:
        return []
    result = await db.execute(
        select(Doctor)
        .join(doctor_dental_services)
        .where(
            doctor_dental_services.c.dental_service_id == service_id,
            Doctor.is_active.is_(True),
        )
        .order_by(Doctor.id)
    )
    return list(result.scalars().all())


async def set_doctor_services(
    db: AsyncSession,
    doctor: Doctor,
    service_ids: list[int],
) -> None:
    unique_ids = list(dict.fromkeys(service_ids))
    if not unique_ids:
        doctor.dental_services = []
        return

    result = await db.execute(
        select(DentalService).where(DentalService.id.in_(unique_ids))
    )
    services_by_id = {service.id: service for service in result.scalars().all()}
    missing_ids = [service_id for service_id in unique_ids if service_id not in services_by_id]
    if missing_ids:
        raise AppError("DENTAL_SERVICE_NOT_FOUND", {"service_ids": missing_ids})

    doctor.dental_services = [services_by_id[service_id] for service_id in unique_ids]
