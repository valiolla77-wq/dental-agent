from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.permissions import (
    ensure_appointment_access,
    ensure_bookable_patient,
    ensure_patient_scope,
)
from app.database import get_db
from app.models.appointment import Appointment
from app.models.user import User
from app.schemas.appointment import (
    AppointmentCreate,
    AppointmentReschedule,
    AppointmentResponse,
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
    )
    return _appointment_response(created)


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
    cancelled = await appointment_service.cancel_appointment(db, appointment_id)
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
