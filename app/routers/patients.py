from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.patient import (
    PatientCreate,
    PatientResponse,
    PatientUpdate,
)
from app.services import patient_service


router = APIRouter(
    prefix="/patients",
    tags=["Patients"],
)


@router.post("/", response_model=PatientResponse)
async def create_patient(
    patient: PatientCreate,
    db: AsyncSession = Depends(get_db),
):
    new_patient = await patient_service.create_patient(
        db=db,
        national_id=patient.national_id,
        full_name=patient.full_name,
        phone=patient.phone,
    )
    return PatientResponse.model_validate(new_patient)


@router.get("/", response_model=List[PatientResponse])
async def get_patients(
    db: AsyncSession = Depends(get_db),
):
    patients = await patient_service.list_patients(db)
    return [PatientResponse.model_validate(patient) for patient in patients]


@router.get("/{patient_id}", response_model=PatientResponse)
async def get_patient(
    patient_id: int,
    db: AsyncSession = Depends(get_db),
):
    patient = await patient_service.get_patient(db, patient_id)
    return PatientResponse.model_validate(patient)


@router.put("/{patient_id}", response_model=PatientResponse)
async def update_patient(
    patient_id: int,
    patient_data: PatientUpdate,
    db: AsyncSession = Depends(get_db),
):
    patient = await patient_service.update_patient(
        db=db,
        patient_id=patient_id,
        full_name=patient_data.full_name,
        phone=patient_data.phone,
    )
    return PatientResponse.model_validate(patient)

@router.delete("/{patient_id}")
async def delete_patient(
    patient_id: int,
    db: AsyncSession = Depends(get_db),
):
    deleted_patient_id = await patient_service.delete_patient(db, patient_id)

    return {
        "message": "بیمار با موفقیت حذف شد.",
        "patient_id": deleted_patient_id,
    }
