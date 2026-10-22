"""Read-only staff workspace. No model/provider calls or patient identifiers in metrics."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.permissions import require_action
from app.database import get_db
from app.models.appointment import Appointment
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.user import User
from app.utils.date_utils import gregorian_to_jalali

router = APIRouter(prefix="/dashboard", tags=["Staff dashboard"])


@router.get("/overview")
async def overview(
    response: Response,
    day: date | None = Query(default=None, ge=date(1900, 1, 1), le=date(2100, 12, 31)),
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    require_action(actor, "appointment:read")
    response.headers["Cache-Control"] = "no-store"
    selected = day or datetime.now(ZoneInfo("Asia/Tehran")).date()
    start = datetime.combine(selected, time.min)
    end = start + timedelta(days=1)
    counts = dict((await db.execute(
        select(Appointment.status, func.count()).where(
            Appointment.appointment_time >= start,
            Appointment.appointment_time < end,
        ).group_by(Appointment.status)
    )).all())
    rows = (await db.execute(
        select(Appointment, Patient.full_name, Doctor.full_name, DentalService.name)
        .join(Patient, Patient.id == Appointment.patient_id)
        .join(Doctor, Doctor.id == Appointment.doctor_id)
        .join(DentalService, DentalService.id == Appointment.service_id)
        .where(Appointment.appointment_time >= start, Appointment.appointment_time < end)
        .order_by(Appointment.appointment_time, Appointment.id)
        .limit(200)
    )).all()
    appointments = []
    for appointment, patient, doctor, service in rows:
        jalali_day, clock = gregorian_to_jalali(appointment.appointment_time)
        appointments.append({
            "id": appointment.id, "patient_name": patient, "doctor_name": doctor,
            "service_name": service, "date": jalali_day, "time": clock,
            "status": appointment.status,
        })
    return {
        "day": selected.isoformat(), "jalali_day": gregorian_to_jalali(start)[0],
        "timezone": "Asia/Tehran", "status_counts": counts,
        "total_appointments": sum(counts.values()),
        "total_patients": await db.scalar(select(func.count()).select_from(Patient)),
        "active_doctors": await db.scalar(select(func.count()).select_from(Doctor).where(Doctor.is_active.is_(True))),
        "appointments": appointments, "truncated": sum(counts.values()) > 200,
    }
