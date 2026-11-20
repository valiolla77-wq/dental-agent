from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.permissions import (
    actor_role,
    ensure_appointment_access,
    ensure_bookable_patient,
    ensure_doctor_listing_scope,
    ensure_patient_scope,
    linked_patient_ids,
    require_action,
)
from app.database import get_db
from app.errors import AppError
from app.models.appointment import Appointment
from app.models.user import User
from app.schemas.appointment import (
    AppointmentCreate,
    AppointmentDetailResponse,
    AppointmentReschedule,
    AppointmentResponse,
    WorklistItemResponse,
)
from app.services import appointment_service, booking_service
from app.utils.date_utils import gregorian_to_jalali

router = APIRouter(
    prefix="/appointments",
    tags=["Appointments"],
)


def _appointment_response(appointment: Appointment) -> AppointmentResponse:
    appointment_date, appointment_time = gregorian_to_jalali(
        appointment.appointment_time
    )
    return AppointmentResponse(
        id=appointment.id,
        patient_id=appointment.patient_id,
        doctor_id=appointment.doctor_id,
        service_id=appointment.service_id,
        appointment_date=appointment_date,
        appointment_time=appointment_time,
        status=appointment.status,
        reason=appointment.reason,
    )


@router.post(
    "/",
    response_model=AppointmentResponse,
)
async def create_appointment(
    appointment: AppointmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Patients may only book for their own linked record; the resolver
    # rejects national-id based identity spoofing for their role.
    patient_id = await ensure_bookable_patient(
        db,
        current_user,
        appointment.patient_id,
        appointment.national_id,
        appointment.full_name,
        appointment.phone,
    )
    created = await booking_service.create_booking(
        db=db,
        patient_id=patient_id,
        national_id=appointment.national_id,
        full_name=appointment.full_name,
        phone=appointment.phone,
        doctor_id=appointment.doctor_id,
        service_id=appointment.service_id,
        appointment_date=appointment.appointment_date,
        appointment_time=appointment.appointment_time,
        reason=appointment.reason,
        actor_role=actor_role(current_user),
    )
    return _appointment_response(created)


@router.get("/", response_model=list[AppointmentDetailResponse])
async def list_appointments(
    doctor_id: int | None = None,
    patient_id: int | None = None,
    appointment_date: str | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Appointment listing for authorized staff, scoped per role.

    Admin/receptionist see the whole clinic (optionally filtered). A doctor
    account is always narrowed server-side to its own linked record; links
    and filters supplied by the client can never widen that scope. Patients
    use ``GET /appointments/me`` instead and are rejected here.
    """
    effective_doctor_id = await ensure_doctor_listing_scope(
        db, current_user, doctor_id
    )
    appointments = await appointment_service.get_appointments_detail(
        db,
        patient_id=patient_id,
        doctor_id=effective_doctor_id,
        appointment_date=appointment_date,
        status=status,
    )
    return [AppointmentDetailResponse.model_validate(item) for item in appointments]


@router.get("/day", response_model=list[WorklistItemResponse])
async def day_worklist(
    appointment_date: str | None = None,
    doctor_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Front-desk worklist for one day (defaults to today in Tehran)."""
    require_action(current_user, "appointment:flow")
    effective_doctor_id = await ensure_doctor_listing_scope(
        db, current_user, doctor_id
    )
    if appointment_date is None:
        now = appointment_service.clinic_now()
        appointment_date, _ = gregorian_to_jalali(now)
    items = await appointment_service.get_day_worklist(
        db,
        appointment_date,
        doctor_id=effective_doctor_id,
    )
    return [WorklistItemResponse.model_validate(item) for item in items]


async def _flow_update(
    db: AsyncSession,
    current_user: User,
    appointment_id: int,
    handler,
):
    await ensure_appointment_access(
        db, current_user, appointment_id, "appointment:read"
    )
    require_action(current_user, "appointment:flow")
    return await handler(db, appointment_id)


@router.post(
    "/{appointment_id}/check-in",
    response_model=WorklistItemResponse,
)
async def check_in(
    appointment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Register arrival and place the patient in today's queue."""
    updated = await _flow_update(
        db,
        current_user,
        appointment_id,
        appointment_service.check_in_appointment,
    )
    items = await appointment_service.get_day_worklist(
        db,
        gregorian_to_jalali(updated.appointment_time)[0],
        doctor_id=updated.doctor_id,
    )
    row = next(item for item in items if item["id"] == updated.id)
    return WorklistItemResponse.model_validate(row)


@router.post(
    "/{appointment_id}/start",
    response_model=WorklistItemResponse,
)
async def start_visit(
    appointment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Move the patient into the treatment room."""
    updated = await _flow_update(
        db,
        current_user,
        appointment_id,
        appointment_service.start_appointment,
    )
    items = await appointment_service.get_day_worklist(
        db,
        gregorian_to_jalali(updated.appointment_time)[0],
        doctor_id=updated.doctor_id,
    )
    row = next(item for item in items if item["id"] == updated.id)
    return WorklistItemResponse.model_validate(row)


@router.post(
    "/{appointment_id}/complete",
    response_model=WorklistItemResponse,
)
async def complete_visit(
    appointment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Close the visit after treatment is finished."""
    updated = await _flow_update(
        db,
        current_user,
        appointment_id,
        appointment_service.complete_appointment,
    )
    items = await appointment_service.get_day_worklist(
        db,
        gregorian_to_jalali(updated.appointment_time)[0],
        doctor_id=updated.doctor_id,
    )
    row = next(item for item in items if item["id"] == updated.id)
    return WorklistItemResponse.model_validate(row)


@router.post(
    "/{appointment_id}/no-show",
    response_model=WorklistItemResponse,
)
async def no_show(
    appointment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Record that the patient never arrived."""
    updated = await _flow_update(
        db,
        current_user,
        appointment_id,
        appointment_service.mark_no_show,
    )
    items = await appointment_service.get_day_worklist(
        db,
        gregorian_to_jalali(updated.appointment_time)[0],
        doctor_id=updated.doctor_id,
    )
    row = next(item for item in items if item["id"] == updated.id)
    return WorklistItemResponse.model_validate(row)


@router.get("/me", response_model=list[AppointmentDetailResponse])
async def my_appointments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Self-service listing for every patient owned by this account.

    The patient ids are resolved from the authenticated session, never from
    the request, so no caller can read another patient's list here.
    """
    if actor_role(current_user) != "patient":
        raise AppError("COMMON_FORBIDDEN")
    linked = await linked_patient_ids(db, current_user)
    if not linked:
        raise AppError("PATIENT_ACCOUNT_NOT_LINKED")
    appointments = await appointment_service.get_appointments_detail(
        db, patient_ids=linked
    )
    return [AppointmentDetailResponse.model_validate(item) for item in appointments]


@router.get(
    "/patient/{patient_id}",
    response_model=list[AppointmentResponse],
)
async def get_patient_appointments(
    patient_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await ensure_patient_scope(db, current_user, patient_id, "appointment:read")
    appointments = await appointment_service.get_patient_appointments(
        db,
        patient_id,
    )
    return [_appointment_response(appointment) for appointment in appointments]


@router.post(
    "/{appointment_id}/cancel",
    response_model=AppointmentResponse,
)
async def cancel_appointment_by_id(
    appointment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cancel a scheduled appointment, subject to role and ownership rules."""
    await ensure_appointment_access(
        db, current_user, appointment_id, "appointment:cancel"
    )
    cancelled = await appointment_service.cancel_appointment(
        db, appointment_id, actor_role=actor_role(current_user)
    )
    return _appointment_response(cancelled)


@router.post(
    "/{appointment_id}/reschedule",
    response_model=AppointmentResponse,
)
async def reschedule_appointment_by_id(
    appointment_id: int,
    payload: AppointmentReschedule,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reschedule a scheduled appointment, subject to role and ownership rules."""
    await ensure_appointment_access(
        db, current_user, appointment_id, "appointment:reschedule"
    )
    moved = await appointment_service.reschedule_appointment(
        db,
        appointment_id,
        payload.appointment_date,
        payload.appointment_time,
        actor_role=actor_role(current_user),
    )
    return _appointment_response(moved)


@router.get("/available-slots/")
async def get_available_slots(
    doctor_id: int,
    appointment_date: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    available_slots = await appointment_service.get_available_slots(
        db,
        doctor_id,
        appointment_date,
    )
    return {
        "doctor_id": doctor_id,
        "date": appointment_date,
        "available_slots": available_slots,
    }
