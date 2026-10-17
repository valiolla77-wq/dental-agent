from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_admin
from app.auth.permissions import (
    ensure_patient_scope,
    linked_patient_id,
    require_action,
)
from app.auth.schemas import LinkUserRequest
from app.database import get_db
from app.errors import AppError
from app.models.patient import Patient
from app.models.user import User
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
    current_user: User = Depends(get_current_user),
):
    require_action(current_user, "patient:create")
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
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "patient":
        # Patients only ever see their own linked record.
        linked = await linked_patient_id(db, current_user)
        if linked is None:
            return []
        patient = await patient_service.get_patient(db, linked)
        return [PatientResponse.model_validate(patient)]
    require_action(current_user, "patient:read")
    patients = await patient_service.list_patients(db)
    return [PatientResponse.model_validate(patient) for patient in patients]


@router.get("/{patient_id}", response_model=PatientResponse)
async def get_patient(
    patient_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await ensure_patient_scope(db, current_user, patient_id, "patient:read")
    patient = await patient_service.get_patient(db, patient_id)
    return PatientResponse.model_validate(patient)


@router.put("/{patient_id}", response_model=PatientResponse)
async def update_patient(
    patient_id: int,
    patient_data: PatientUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await ensure_patient_scope(db, current_user, patient_id, "patient:update")
    patient = await patient_service.update_patient(
        db=db,
        patient_id=patient_id,
        full_name=patient_data.full_name,
        phone=patient_data.phone,
    )
    return PatientResponse.model_validate(patient)

@router.post(
    "/{patient_id}/link-user",
    response_model=PatientResponse,
)
async def link_patient_user(
    patient_id: int,
    payload: LinkUserRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Staff-assisted link between a patient record and a patient account.

    Admin only. Never links by guesswork: the target user must already exist
    with the ``patient`` role, the record must be unlinked, and the account
    must not already own another record.
    """
    require_action(current_user, "patient:link")
    patient = await db.get(Patient, patient_id)
    if patient is None:
        raise AppError("PATIENT_NOT_FOUND")
    if patient.user_id is not None:
        raise AppError("COMMON_CONFLICT")
    result = await db.execute(select(User).where(User.phone == payload.phone))
    target = result.scalar_one_or_none()
    if target is None or target.role != "patient" or not target.is_active:
        raise AppError("COMMON_VALIDATION_ERROR")
    existing = await db.execute(
        select(Patient).where(Patient.user_id == target.id)
    )
    if existing.scalar_one_or_none() is not None:
        raise AppError("COMMON_CONFLICT")
    patient.user_id = target.id
    await db.commit()
    await db.refresh(patient)
    return PatientResponse.model_validate(patient)


@router.delete("/{patient_id}")
async def delete_patient(
    patient_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    deleted_patient_id = await patient_service.delete_patient(db, patient_id)

    return {
        "message": "بیمار با موفقیت حذف شد.",
        "patient_id": deleted_patient_id,
    }
