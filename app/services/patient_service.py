"""Patient domain operations and persistence."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.models.patient import Patient


async def create_patient(
    db: AsyncSession,
    national_id: str,
    full_name: str,
    phone: str,
    *,
    commit: bool = True,
) -> Patient:
    result = await db.execute(
        select(Patient).where(Patient.national_id == national_id)
    )
    existing_patient = result.scalar_one_or_none()

    if existing_patient:
        raise AppError("PATIENT_DUPLICATE_NATIONAL_ID")

    new_patient = Patient(
        national_id=national_id,
        full_name=full_name,
        phone=phone,
    )
    db.add(new_patient)

    if commit:
        await db.commit()
        await db.refresh(new_patient)
    else:
        await db.flush()
    return new_patient


async def get_patient_by_national_id(
    db: AsyncSession,
    national_id: str,
) -> Patient | None:
    result = await db.execute(
        select(Patient).where(Patient.national_id == national_id)
    )
    return result.scalar_one_or_none()


async def list_patients(db: AsyncSession) -> list[Patient]:
    result = await db.execute(select(Patient).order_by(Patient.id))
    return list(result.scalars().all())


async def get_patient(db: AsyncSession, patient_id: int) -> Patient:
    result = await db.execute(
        select(Patient).where(Patient.id == patient_id)
    )
    patient = result.scalar_one_or_none()

    if patient is None:
        raise AppError("PATIENT_NOT_FOUND")

    return patient


async def update_patient(
    db: AsyncSession,
    patient_id: int,
    full_name: str,
    phone: str,
) -> Patient:
    patient = await get_patient(db, patient_id)
    patient.full_name = full_name
    patient.phone = phone

    await db.commit()
    await db.refresh(patient)
    return patient


async def delete_patient(db: AsyncSession, patient_id: int) -> int:
    patient = await get_patient(db, patient_id)
    await db.delete(patient)
    await db.commit()
    return patient_id
