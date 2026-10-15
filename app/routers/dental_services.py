from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.database import get_db
from app.models.user import User
from app.schemas.dental_service import (
    DentalServiceCreate,
    DentalServiceResponse,
    DentalServiceUpdate,
)
from app.schemas.doctor import DoctorResponse
from app.services import dental_service_service


router = APIRouter(
    prefix="/dental-services",
    tags=["Dental Services"],
)


@router.post("/", response_model=DentalServiceResponse)
async def create_dental_service(
    service: DentalServiceCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    created = await dental_service_service.create_dental_service(
        db,
        service.name,
        service.description,
    )
    return DentalServiceResponse.model_validate(created)


@router.get("/", response_model=list[DentalServiceResponse])
async def list_dental_services(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
):
    services = await dental_service_service.list_dental_services(
        db,
        active_only=active_only,
    )
    return [DentalServiceResponse.model_validate(service) for service in services]


@router.get("/{service_id}/doctors", response_model=list[DoctorResponse])
async def get_service_doctors(
    service_id: int,
    db: AsyncSession = Depends(get_db),
):
    doctors = await dental_service_service.get_service_doctors(db, service_id)
    return [DoctorResponse.model_validate(doctor) for doctor in doctors]


@router.get("/{service_id}", response_model=DentalServiceResponse)
async def get_dental_service(
    service_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = await dental_service_service.get_dental_service(db, service_id)
    return DentalServiceResponse.model_validate(service)


@router.put("/{service_id}", response_model=DentalServiceResponse)
async def update_dental_service(
    service_id: int,
    service_data: DentalServiceUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    service = await dental_service_service.update_dental_service(
        db=db,
        service_id=service_id,
        name=service_data.name,
        description=service_data.description,
        is_active=service_data.is_active,
    )
    return DentalServiceResponse.model_validate(service)


@router.delete("/{service_id}")
async def delete_dental_service(
    service_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    deleted_id = await dental_service_service.delete_dental_service(
        db,
        service_id,
    )
    return {
        "message": "خدمت دندانپزشکی با موفقیت حذف شد.",
        "service_id": deleted_id,
    }
