"""Persian confirmation prompts describing a pending write."""

import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.patient_binding import _is_patient_actor
from app.agent.state import PendingAction
from app.errors import AppError
from app.models.appointment import Appointment
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.user import User
from app.services.appointment_service import validate_appointment_slot
from app.utils.date_utils import gregorian_to_jalali
from app.utils.persian import to_persian_digits

_FEEDBACK_LABELS = {"error": "گزارش خطا", "suggestion": "پیشنهاد"}


def _mask_national_id_tail(national_id: str | None) -> str | None:
    """Short non-identifying tail for confirmation prompts (never the full id)."""
    if not national_id:
        return None
    digits = "".join(char for char in str(national_id) if char.isdigit())
    if len(digits) < 4:
        return "***"
    return f"***{digits[-3:]}"


def _confirmation_prompt(action: PendingAction) -> str:
    """Safe id-based fallback used only when no richer description is possible."""
    name = action.get("tool_name")
    args = action.get("arguments") or {}
    labels = {
        "book_appointment": "ثبت نوبت",
        "cancel_appointment": "لغو نوبت",
        "reschedule_appointment": "جابه‌جایی نوبت",
        "create_patient": "ثبت پروندهٔ جدید",
        "update_patient": "ویرایش پرونده",
        "submit_feedback": "ثبت بازخورد",
    }
    summary = labels.get(name, "اجرای عملیات")
    if name == "book_appointment":
        summary += (
            f" برای پزشک {args.get('doctor_id', 'نامشخص')}"
            f" و خدمت {args.get('service_id', 'نامشخص')}"
            f" در تاریخ {args.get('appointment_date', 'نامشخص')}"
            f" ساعت {args.get('appointment_time', 'نامشخص')}"
        )
    elif name == "reschedule_appointment":
        summary += (
            f" به تاریخ {args.get('appointment_date', 'نامشخص')} ساعت "
            f"{args.get('appointment_time', 'نامشخص')}"
        )
    return f"برای {summary} تأیید می‌کنید؟"


async def _describe_action(
    db: AsyncSession,
    action: PendingAction,
    actor: User | None,
    *,
    now: datetime | None = None,
) -> str:
    """Build a human-readable confirmation from trusted database records.

    Names, services and current times come from the database, never from the
    model or client. Missing records raise a catalogued ``AppError`` so a
    confirmation with guessed text is never shown.
    """
    name = action.get("tool_name")
    args = action.get("arguments") or {}

    if name == "book_appointment":
        doctor_id = args.get("doctor_id")
        service_id = args.get("service_id")
        doctor = await db.get(Doctor, doctor_id) if isinstance(doctor_id, int) else None
        service = (
            await db.get(DentalService, service_id)
            if isinstance(service_id, int)
            else None
        )
        if doctor is None:
            raise AppError("DOCTOR_NOT_FOUND")
        if service is None:
            raise AppError("DENTAL_SERVICE_NOT_FOUND")
        if not doctor.is_active:
            raise AppError("DOCTOR_INACTIVE")
        if not service.is_active:
            raise AppError("APPOINTMENT_SERVICE_INACTIVE")

        # Validate the requested slot before showing a confirmation. The write
        # still revalidates atomically, but the user must never be asked to
        # approve an already-booked or malformed slot.
        slot = await validate_appointment_slot(
            db,
            doctor.id,
            service.id,
            str(args.get("appointment_date", "")),
            str(args.get("appointment_time", "")),
            now=now,
        )
        appointment_date, appointment_time = (
            to_persian_digits(part) for part in gregorian_to_jalali(slot)
        )

        summary = (
            f"ثبت نوبت برای «{service.name}» با {doctor.full_name} "
            f"در تاریخ {appointment_date} ساعت {appointment_time}"
        )
        if not _is_patient_actor(actor):
            patient_id = args.get("patient_id")
            if isinstance(patient_id, int):
                patient = await db.get(Patient, patient_id)
                if patient is None:
                    raise AppError("PATIENT_NOT_FOUND")
                summary += f" برای {patient.full_name}"
            else:
                national_id = args.get("national_id")
                patient = (
                    await db.scalar(
                        select(Patient).where(
                            Patient.national_id == national_id
                        )
                    )
                    if national_id
                    else None
                )
                if patient is not None:
                    summary += f" برای {patient.full_name}"
                elif args.get("full_name"):
                    summary += f" برای {args['full_name']} (بیمار جدید)"
                else:
                    raise AppError("COMMON_VALIDATION_ERROR")
        return f"{summary} را تأیید می‌کنید؟"

    if name in {"cancel_appointment", "reschedule_appointment"}:
        appointment_id = args.get("appointment_id")
        appointment = (
            await db.get(Appointment, appointment_id)
            if isinstance(appointment_id, int)
            else None
        )
        if appointment is None:
            raise AppError("APPOINTMENT_NOT_FOUND")
        if name == "cancel_appointment":
            if appointment.status == "cancelled":
                raise AppError("APPOINTMENT_ALREADY_CANCELLED")
            if appointment.status != "scheduled":
                raise AppError("APPOINTMENT_NOT_CANCELLABLE")
        elif appointment.status != "scheduled":
            raise AppError("APPOINTMENT_NOT_RESCHEDULABLE")
        current_date, current_time = (
            to_persian_digits(part)
            for part in gregorian_to_jalali(appointment.appointment_time)
        )
        doctor = await db.get(Doctor, appointment.doctor_id)
        service = await db.get(DentalService, appointment.service_id)
        doctor_name = doctor.full_name if doctor is not None else "پزشک ثبت‌شده"
        service_name = service.name if service is not None else "خدمت ثبت‌شده"

        if name == "cancel_appointment":
            return (
                f"لغو نوبت «{service_name}» با {doctor_name} در تاریخ "
                f"{current_date} ساعت {current_time} را تأیید می‌کنید؟"
            )

        target = await validate_appointment_slot(
            db,
            appointment.doctor_id,
            appointment.service_id,
            str(args.get("appointment_date", "")),
            str(args.get("appointment_time", "")),
            exclude_appointment_id=appointment.id,
            now=now,
        )
        target_date, target_time = (
            to_persian_digits(part) for part in gregorian_to_jalali(target)
        )
        return (
            f"جابه‌جایی نوبت «{service_name}» با {doctor_name} از تاریخ "
            f"{current_date} ساعت {current_time} به تاریخ {target_date} "
            f"ساعت {target_time} را تأیید می‌کنید؟"
        )

    if name == "create_patient":
        national_id = args.get("national_id")
        masked = _mask_national_id_tail(national_id)
        summary = (
            f"ثبت پروندهٔ جدید برای «{args.get('full_name', 'نامشخص')}» "
            f"با تلفن {args.get('phone', 'نامشخص')}"
        )
        if masked:
            summary += f" و کد ملی پوشانده‌شده {to_persian_digits(masked)}"
        return f"{summary} را تأیید می‌کنید؟"

    if name == "update_patient":
        patient_id = args.get("patient_id")
        patient = (
            await db.get(Patient, patient_id)
            if isinstance(patient_id, int)
            else None
        )
        if patient is None:
            raise AppError("PATIENT_NOT_FOUND")
        changes: list[str] = []
        if args.get("full_name") and args["full_name"] != patient.full_name:
            changes.append(f"نام به «{args['full_name']}»")
        if args.get("phone") and args["phone"] != patient.phone:
            changes.append(f"تلفن به {args['phone']}")
        if args.get("national_id") and args["national_id"] != patient.national_id:
            masked = _mask_national_id_tail(args["national_id"])
            if masked:
                changes.append(
                    f"کد ملی به {to_persian_digits(masked)}"
                )
        if not changes:
            raise AppError("COMMON_VALIDATION_ERROR")
        return (
            f"ویرایش پروندهٔ «{patient.full_name}» با "
            f"{' و '.join(changes)} را تأیید می‌کنید؟"
        )

    if name == "submit_feedback":
        category = str(args.get("category", ""))
        label = _FEEDBACK_LABELS.get(category, "بازخورد")
        message = str(args.get("message", "")).strip()
        preview = message[:120] + ("…" if len(message) > 120 else "")
        return (
            f"ثبت {label} با متن «{preview}» برای تیم پشتیبانی را "
            "تأیید می‌کنید؟"
        )

    return _confirmation_prompt(action)


def _target_selection_text(tool_name: str, text: str) -> str:
    """Drop a reschedule destination clause before matching the current row.

    ``نوبت ۱۰ را به ۱۱ منتقل کن`` names the current slot before ``به`` and the
    new slot after it. Only the former may identify the target; otherwise the
    destination date/time would filter out the row the user wants to move.
    """
    if tool_name != "reschedule_appointment":
        return text
    before_destination = re.split(r"\s+به\s+", text, maxsplit=1)[0]
    return before_destination if before_destination.strip() else text
