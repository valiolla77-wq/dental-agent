"""Booking flow orchestration across patient and appointment services.

Transaction ownership: mutating service functions own the session's
transaction boundary. They commit once after all writes succeed and roll back
on any failure, so they work whether the caller's session is fresh or already
has a read transaction open (for example after an authorization query).
Callers must not hold unrelated uncommitted writes when invoking this service.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.models.appointment import Appointment
from app.services import appointment_service, patient_service


async def create_booking(
    db: AsyncSession,
    doctor_id: int,
    service_id: int,
    appointment_date: str,
    appointment_time: str,
    *,
    patient_id: int | None = None,
    national_id: str | None = None,
    full_name: str | None = None,
    phone: str | None = None,
    reason: str | None = None,
) -> Appointment:
    """Reuse or create a patient and book atomically using domain services."""
    try:
        if patient_id is None:
            if not all(
                value and value.strip()
                for value in (national_id, full_name, phone)
            ):
                # The API schema validates this too; keep service callers safe.
                raise AppError("COMMON_VALIDATION_ERROR")

            patient = await patient_service.get_patient_by_national_id(
                db,
                national_id,
            )
            if patient is None:
                patient = await patient_service.create_patient(
                    db,
                    national_id,
                    full_name,
                    phone,
                    commit=False,
                )
            patient_id = patient.id

        appointment = await appointment_service.create_appointment(
            db=db,
            patient_id=patient_id,
            doctor_id=doctor_id,
            service_id=service_id,
            appointment_date=appointment_date,
            appointment_time=appointment_time,
            reason=reason,
            commit=False,
        )

        # Commit the whole booking (optional new patient + appointment) once.
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    await db.refresh(appointment)
    return appointment
