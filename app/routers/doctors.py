from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.database import get_db
from app.models.user import User
from app.schemas.doctor import (
    DoctorCreate,
    DoctorResponse,
    DoctorUpdate,
)
from app.schemas.dental_service import DentalServiceResponse
from app.services import doctor_service
from app.services import dental_service_service


router = APIRouter(
    prefix="/doctors",
    tags=["Doctors"],
)


@router.post("/", response_model=DoctorResponse)
async def create_doctor(
    doctor: DoctorCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    new_doctor = await doctor_service.create_doctor(
        db=db,
        full_name=doctor.full_name,
        specialty=doctor.specialty,
        phone=doctor.phone,
        service_ids=doctor.service_ids,
    )
    return DoctorResponse.model_validate(new_doctor)


@router.put("/{doctor_id}", response_model=DoctorResponse)
async def update_doctor(
    doctor_id: int,
    doctor: DoctorUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    updated_doctor = await doctor_service.update_doctor(
        db=db,
        doctor_id=doctor_id,
        full_name=doctor.full_name,
        specialty=doctor.specialty,
        phone=doctor.phone,
        is_active=doctor.is_active,
        service_ids=doctor.service_ids,
    )
    return DoctorResponse.model_validate(updated_doctor)


@router.get(
    "/{doctor_id}/services",
    response_model=list[DentalServiceResponse],
)
async def get_doctor_services(
    doctor_id: int,
    db: AsyncSession = Depends(get_db),
):
    return await dental_service_service.get_doctor_services(db, doctor_id)
