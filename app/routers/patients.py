from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.patient import Patient
from app.schemas.patient import (
    PatientCreate,
    PatientResponse,
    PatientUpdate,
)
from app.errors import AppError


router = APIRouter(
    prefix="/patients",
    tags=["Patients"],
)


@router.post("/", response_model=PatientResponse)
async def create_patient(
    patient: PatientCreate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Patient).where(
            Patient.national_id == patient.national_id
        )
    )

    existing_patient = result.scalar_one_or_none()

    if existing_patient:
        raise AppError("PATIENT_DUPLICATE_NATIONAL_ID")

    new_patient = Patient(
        national_id=patient.national_id,
        full_name=patient.full_name,
        phone=patient.phone,
    )

    db.add(new_patient)

    await db.commit()
    await db.refresh(new_patient)

    return new_patient


@router.get("/", response_model=List[PatientResponse])
async def get_patients(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Patient).order_by(Patient.id)
    )

    patients = result.scalars().all()

    return patients


@router.get("/{patient_id}", response_model=PatientResponse)
async def get_patient(
    patient_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Patient).where(
            Patient.id == patient_id
        )
    )

    patient = result.scalar_one_or_none()

    if patient is None:
        raise AppError("PATIENT_NOT_FOUND")

    return patient


@router.put("/{patient_id}", response_model=PatientResponse)
async def update_patient(
    patient_id: int,
    patient_data: PatientUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Patient).where(
            Patient.id == patient_id
        )
    )

    patient = result.scalar_one_or_none()

    if patient is None:
        raise AppError("PATIENT_NOT_FOUND")

    patient.full_name = patient_data.full_name
    patient.phone = patient_data.phone

    await db.commit()
    await db.refresh(patient)

    return patient

@router.delete("/{patient_id}")
async def delete_patient(
    patient_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Patient).where(
            Patient.id == patient_id
        )
    )

    patient = result.scalar_one_or_none()

    if patient is None:
        raise AppError("PATIENT_NOT_FOUND")

    await db.delete(patient)
    await db.commit()

    return {
        "message": "بیمار با موفقیت حذف شد.",
        "patient_id": patient_id,
    }
