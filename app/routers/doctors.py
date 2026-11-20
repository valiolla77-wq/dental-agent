from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_admin
from app.auth.schemas import LinkUserRequest
from app.database import get_db
from app.errors import AppError
from app.models.doctor import Doctor
from app.models.doctor_dental_service import doctor_dental_services
from app.models.user import User
from app.schemas.dental_service import DentalServiceResponse
from app.schemas.doctor import (
    DoctorCreate,
    DoctorPublicResponse,
    DoctorResponse,
    DoctorUpdate,
)
from app.services import dental_service_service, doctor_service
from app.services.audit_service import record_audit

router = APIRouter(
    prefix="/doctors",
    tags=["Doctors"],
)


@router.get("/", response_model=list[DoctorPublicResponse])
async def list_doctors(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Doctor catalog for authenticated users; phone numbers never leave here."""
    doctors = await doctor_service.list_doctors(db, active_only=active_only)
    return [DoctorPublicResponse.model_validate(doctor) for doctor in doctors]


async def _service_ids_by_doctor(db: AsyncSession) -> dict[int, list[int]]:
    """Doctor-id -> offered service ids, from the association table.

    Deliberately avoids lazy-loading the ORM relationship, which cannot run
    inside the async request context (MissingGreenlet).
    """
    result = await db.execute(select(doctor_dental_services))
    mapping: dict[int, list[int]] = {}
    for row in result:
        mapping.setdefault(int(row.doctor_id), []).append(int(row.dental_service_id))
    return mapping


@router.get("/manage", response_model=list[DoctorResponse])
async def list_doctors_for_management(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Admin-only management listing: contact data, account and service links.

    The public catalog endpoint scrubs the phone for every role (see
    tests/test_catalog_privacy.py); the back-office needs the full picture in
    one call so the management table does not resort to N+1 reads.
    """
    doctors = await doctor_service.list_doctors(db, active_only=False)
    service_map = await _service_ids_by_doctor(db)
    items: list[DoctorResponse] = []
    for doctor in doctors:
        item = DoctorResponse.model_validate(doctor)
        item.service_ids = service_map.get(int(doctor.id), [])
        items.append(item)
    return items


@router.get("/{doctor_id}", response_model=DoctorPublicResponse)
async def get_doctor(
    doctor_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """One public catalog record; same no-phone contract as the listing."""
    doctor = await doctor_service.get_doctor(db, doctor_id)
    return DoctorPublicResponse.model_validate(doctor)


@router.get("/{doctor_id}/manage", response_model=DoctorResponse)
async def get_doctor_for_management(
    doctor_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Admin-only full record (phone included) for the edit form.

    The public catalog endpoints deliberately scrub the phone for every role
    (see tests/test_catalog_privacy.py); this management read is the single
    admin door that keeps contact data available for maintenance.
    """
    doctor = await doctor_service.get_doctor(db, doctor_id)
    result = await db.execute(
        select(doctor_dental_services.c.dental_service_id).where(
            doctor_dental_services.c.doctor_id == doctor_id
        )
    )
    item = DoctorResponse.model_validate(doctor)
    item.service_ids = [int(row) for row in result.scalars().all()]
    return item


@router.post("/{doctor_id}/link-user", response_model=DoctorResponse)
async def link_doctor_user(
    doctor_id: int,
    payload: LinkUserRequest,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_admin),
):
    """Admin-assisted link between a doctor record and a doctor account.

    Never links by guesswork: the target user must already exist with the
    ``doctor`` role, the record must be unlinked, the account must not
    already own another record, and the account phone must match the phone
    stored on the doctor record.
    """
    doctor = await db.get(Doctor, doctor_id)
    if doctor is None:
        raise AppError("DOCTOR_NOT_FOUND")
    if doctor.user_id is not None:
        raise AppError("COMMON_CONFLICT")

    account_phone = (payload.phone or "").strip()
    record_phone = (doctor.phone or "").strip()
    if not account_phone or account_phone != record_phone:
        raise AppError("COMMON_VALIDATION_ERROR")

    result = await db.execute(select(User).where(User.phone == account_phone))
    target = result.scalar_one_or_none()
    if target is None or target.role != "doctor" or not target.is_active:
        raise AppError("COMMON_VALIDATION_ERROR")
    existing = await db.execute(
        select(Doctor).where(Doctor.user_id == target.id)
    )
    if existing.scalar_one_or_none() is not None:
        raise AppError("COMMON_CONFLICT")

    doctor.user_id = target.id
    try:
        await db.commit()
    except IntegrityError:
        # The unique index on doctors.user_id is the final authority under
        # concurrent admin requests. Preserve the record and fail closed.
        await db.rollback()
        raise AppError("COMMON_CONFLICT") from None
    await db.refresh(doctor)

    await record_audit(
        db,
        actor=target,
        action="doctor.link_user",
        target_user_id=int(target.id),
        target_label=f"{doctor.full_name} (پزشک #{doctor.id})",
        detail={"doctor_id": int(doctor.id), "user_id": int(target.id)},
    )
    await db.commit()
    return DoctorResponse.model_validate(doctor)


@router.post("/", response_model=DoctorResponse)
async def create_doctor(
    doctor: DoctorCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    new_doctor = await doctor_service.create_doctor(
        db=db,
        full_name=doctor.full_name,
        specialty=doctor.specialty,
        phone=doctor.phone,
        service_ids=doctor.service_ids,
    )
    await record_audit(
        db,
        actor=admin,
        action="doctor.create",
        target_label=f"{new_doctor.full_name} (پزشک #{new_doctor.id})",
        detail={"doctor_id": int(new_doctor.id), "specialty": new_doctor.specialty},
    )
    await db.commit()
    return DoctorResponse.model_validate(new_doctor)


@router.put("/{doctor_id}", response_model=DoctorResponse)
async def update_doctor(
    doctor_id: int,
    doctor: DoctorUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
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
    await record_audit(
        db,
        actor=admin,
        action="doctor.update",
        target_label=f"{updated_doctor.full_name} (پزشک #{updated_doctor.id})",
        detail={
            "doctor_id": int(updated_doctor.id),
            "is_active": bool(updated_doctor.is_active),
        },
    )
    await db.commit()
    return DoctorResponse.model_validate(updated_doctor)


@router.get(
    "/{doctor_id}/services",
    response_model=list[DentalServiceResponse],
)
async def get_doctor_services(
    doctor_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    # Service catalog for one doctor: no doctor PII in the response, but the
    # endpoint is limited to authenticated users like the rest of the catalog.
    return await dental_service_service.get_doctor_services(db, doctor_id)
