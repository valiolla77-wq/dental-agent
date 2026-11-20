
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_admin
from app.auth.permissions import (
    ensure_patient_scope,
    linked_patient_ids,
    require_action,
    require_role_present,
)
from app.auth.schemas import LinkUserRequest
from app.database import get_db
from app.errors import AppError
from app.models.patient import Patient
from app.models.user import User
from app.schemas.patient import (
    PatientCreate,
    PatientResponse,
    PatientSelfRegister,
    PatientUpdate,
)
from app.services import patient_service
from app.services.audit_service import record_audit

router = APIRouter(
    prefix="/patients",
    tags=["Patients"],
)


def _account_phone_digits(phone: str | None) -> str:
    """Digits-only phone form used for exact account/record comparisons."""
    return "".join(char for char in (phone or "") if char.isdigit())


@router.post(
    "/me",
    response_model=PatientResponse,
    status_code=201,
)
async def create_initial_record(
    payload: PatientSelfRegister,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Register a patient record under the authenticated patient account.

    ``relation="self"`` creates the single account-holder record and requires
    the account phone. ``relation="other"`` registers a family/dependent with
    its own unique phone. Every registration requires a valid national id.
    The account link is always server-side from the token.
    """
    require_role_present(current_user, "patient")

    submitted = _account_phone_digits(payload.phone)
    account = _account_phone_digits(current_user.phone)
    if not submitted or not account:
        raise AppError("COMMON_VALIDATION_ERROR")
    if payload.relation == "self" and submitted != account:
        raise AppError("COMMON_VALIDATION_ERROR")
    if payload.relation == "other" and submitted == account:
        raise AppError("COMMON_VALIDATION_ERROR")

    patient = await patient_service.create_initial_record(
        db=db,
        user_id=current_user.id,
        full_name=payload.full_name,
        phone=payload.phone,
        national_id=payload.national_id,
        relation=payload.relation,
        account_phone=current_user.phone,
    )
    return PatientResponse.model_validate(patient)


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


@router.get("/", response_model=list[PatientResponse])
async def get_patients(
    search: str | None = None,
    record_status: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "patient":
        # Patients only ever see their own linked records; a search term is
        # ignored for their role so scoping can never be widened client-side.
        linked_ids = await linked_patient_ids(db, current_user)
        if not linked_ids:
            # No record yet: the client shows the registration form and does
            # not start a chat.
            return []
        patients = [
            await patient_service.get_patient(db, patient_id)
            for patient_id in linked_ids
        ]
        return [PatientResponse.model_validate(patient) for patient in patients]
    require_action(current_user, "patient:read")
    patients = await patient_service.list_patients(
        db, search=search, record_status=record_status
    )
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
        national_id=patient_data.national_id,
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
    phone must match the phone stored on the record. An account may already
    own family records; only a second *account-holder* record is rejected.
    """
    require_action(current_user, "patient:link")
    patient = await db.get(Patient, patient_id)
    if patient is None:
        raise AppError("PATIENT_NOT_FOUND")
    if patient.user_id is not None:
        raise AppError("COMMON_CONFLICT")

    account_phone = _account_phone_digits(payload.phone)
    record_phone = _account_phone_digits(patient.phone)
    if not account_phone or account_phone != record_phone:
        raise AppError("COMMON_VALIDATION_ERROR")

    result = await db.execute(select(User).where(User.phone == payload.phone.strip()))
    target = result.scalar_one_or_none()
    if target is None or target.role != "patient" or not target.is_active:
        raise AppError("COMMON_VALIDATION_ERROR")
    existing_holder = await db.execute(
        select(Patient).where(
            Patient.user_id == target.id,
            Patient.is_account_holder.is_(True),
        )
    )
    if existing_holder.scalar_one_or_none() is not None:
        raise AppError("COMMON_CONFLICT")

    patient.user_id = target.id
    patient.is_account_holder = True
    try:
        await db.commit()
    except IntegrityError:
        # The partial unique account-holder index is the final authority under
        # concurrent admin requests. Preserve the record and fail closed.
        await db.rollback()
        raise AppError("COMMON_CONFLICT") from None
    await db.refresh(patient)
    return PatientResponse.model_validate(patient)


@router.delete("/{patient_id}")
async def delete_patient(
    patient_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    deleted_patient_id = await patient_service.delete_patient(db, patient_id)

    await record_audit(
        db,
        actor=admin,
        action="patient.delete",
        target_label=f"پرونده بیمار #{deleted_patient_id}",
        detail={"patient_id": deleted_patient_id},
    )
    await db.commit()

    return {
        "message": "بیمار با موفقیت حذف شد.",
        "patient_id": deleted_patient_id,
    }
