"""In-app notification composition and delivery.

All writes happen inside the caller's transaction (flush, never commit) so a
business change and its notification land atomically — except the lazy
reminder builder, which is documented separately and commits itself.

Recipients matrix for appointment events:

- actor is a patient account → every active ``admin``/``receptionist``
  account is notified (the front desk must know about self-service changes).
- actor is staff (or unknown/system) → the patient record's owning account
  is notified, so family-account holders see changes for their dependants.

Notification creation is deliberately best-effort: a failure to compose a
notification must never fail the booking/cancellation it describes, so the
helpers swallow unexpected lookup errors after logging them.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment
from app.models.dental_service import DentalService
from app.models.notification import Notification
from app.models.patient import Patient
from app.models.user import User
from app.utils.date_utils import gregorian_to_jalali

logger = logging.getLogger(__name__)

_APPOINTMENT_EVENT_KINDS: dict[str, str] = {
    "booked": "appointment_booked",
    "cancelled": "appointment_cancelled",
    "rescheduled": "appointment_rescheduled",
}

# Persian copy per (event, audience). {patient}, {service}, {when} are filled
# by _appointment_copy(); the "when" fragment is a Jalali date + time.
_EVENT_TITLES: dict[tuple[str, str], str] = {
    ("booked", "patient"): "نوبت شما ثبت شد",
    ("booked", "staff"): "نوبت جدید ثبت شد",
    ("cancelled", "patient"): "نوبت شما لغو شد",
    ("cancelled", "staff"): "نوبت توسط بیمار لغو شد",
    ("rescheduled", "patient"): "زمان نوبت شما تغییر کرد",
    ("rescheduled", "staff"): "زمان نوبت توسط بیمار تغییر کرد",
}

_EVENT_BODIES: dict[tuple[str, str], str] = {
    ("booked", "patient"): "نوبت «{service}» برای {patient} در {when} ثبت شد.",
    ("booked", "staff"): "{patient} برای «{service}» در {when} نوبت گرفت.",
    ("cancelled", "patient"): "نوبت «{service}» برای {patient} در {when} لغو شد. برای مراقبت بعدی نوبت جدید رزرو کنید.",
    ("cancelled", "staff"): "نوبت {patient} برای «{service}» در {when} لغو شد.",
    ("rescheduled", "patient"): "نوبت «{service}» برای {patient} به {when} منتقل شد.",
    ("rescheduled", "staff"): "نوبت {patient} برای «{service}» به {when} منتقل شد.",
}


def _utc_now_naive() -> datetime:

    return datetime.now(UTC).replace(tzinfo=None)


def _appointment_copy(
    appointment: Appointment,
    *,
    patient_name: str,
    service_name: str,
) -> str:
    appointment_date, appointment_time = gregorian_to_jalali(
        appointment.appointment_time
    )
    return f"{appointment_date} ساعت {appointment_time[:5]}"


async def _active_staff_ids(db: AsyncSession) -> list[int]:
    result = await db.execute(
        select(User.id).where(
            User.role.in_(("admin", "receptionist")),
            User.is_active.is_(True),
        )
    )
    return [int(row) for row in result.scalars().all()]


def _add_notification(
    db: AsyncSession,
    *,
    user_id: int,
    kind: str,
    title: str,
    body: str | None,
    appointment_id: int | None,
) -> None:
    db.add(
        Notification(
            user_id=user_id,
            kind=kind,
            title=title[:200],
            body=body[:500] if body else None,
            appointment_id=appointment_id,
            is_read=False,
            created_at=_utc_now_naive(),
        )
    )


async def notify_appointment_event(
    db: AsyncSession,
    appointment: Appointment,
    *,
    event: str,
    actor_role: str | None,
) -> None:
    """Queue one notification per affected account inside the caller's txn.

    Called by the booking/cancellation/reschedule services just before their
    single commit. Any unexpected error is logged and swallowed: the domain
    change must survive even if notification composition fails.
    """
    kind = _APPOINTMENT_EVENT_KINDS.get(event)
    if kind is None:
        logger.warning("Unknown appointment notification event: %s", event)
        return
    try:
        patient = await db.get(Patient, appointment.patient_id)
        service = await db.get(DentalService, appointment.service_id)
        patient_name = patient.full_name if patient else "بیمار"
        service_name = service.name if service else "خدمت دندانپزشکی"
        when = _appointment_copy(appointment, patient_name=patient_name, service_name=service_name)

        if actor_role == "patient":
            for user_id in await _active_staff_ids(db):
                _add_notification(
                    db,
                    user_id=user_id,
                    kind=kind,
                    title=_EVENT_TITLES[(event, "staff")],
                    body=_EVENT_BODIES[(event, "staff")].format(
                        patient=patient_name, service=service_name, when=when
                    ),
                    appointment_id=appointment.id,
                )
            return

        audience = "patient"
        if patient is not None and patient.user_id is not None:
            _add_notification(
                db,
                user_id=int(patient.user_id),
                kind=kind,
                title=_EVENT_TITLES[(event, audience)],
                body=_EVENT_BODIES[(event, audience)].format(
                    patient=patient_name, service=service_name, when=when
                ),
                appointment_id=appointment.id,
            )
    except Exception:  # pragma: no cover - defensive: never break the booking
        logger.exception("Failed to compose appointment notification")


def reminder_copy(appointment: Appointment, patient_name: str, service_name: str) -> tuple[str, str]:
    """Persian title/body for the 24-hour appointment reminder."""
    appointment_date, appointment_time = gregorian_to_jalali(
        appointment.appointment_time
    )
    when = f"{appointment_date} ساعت {appointment_time[:5]}"
    title = "یادآوری نوبت"
    body = (
        f"نوبت «{service_name}» برای {patient_name} {when} است. "
        "لطفاً چند دقیقه قبل در کلینیک حاضر شوید."
    )
    return title, body


async def ensure_upcoming_reminders(
    db: AsyncSession,
    *,
    user_id: int,
    linked_patient_ids: list[int],
    now: datetime | None = None,
) -> int:
    """Create 24-hour reminders once per appointment; commits on success.

    Idempotent by (user_id, kind='reminder', appointment_id): the listing
    endpoint may call it on every load but each appointment reminds at most
    once per account. Uses Tehran wall-clock semantics identical to the
    booking services.
    """
    from app.services.appointment_service import clinic_now

    if not linked_patient_ids:
        return 0
    current = clinic_now(now)
    window_end = current + timedelta(hours=24)

    try:
        upcoming_rows = (
            await db.execute(
                select(Appointment, Patient, DentalService)
                .join(Patient, Appointment.patient_id == Patient.id)
                .join(DentalService, Appointment.service_id == DentalService.id)
                .where(
                    Appointment.patient_id.in_(linked_patient_ids),
                    Appointment.status == "scheduled",
                    Appointment.appointment_time > current,
                    Appointment.appointment_time <= window_end,
                )
                .order_by(Appointment.appointment_time)
            )
        ).all()
        upcoming = [
            (appointment, patient, service)
            for appointment, patient, service in upcoming_rows
        ]

        if not upcoming:
            return 0

        existing = (
            await db.execute(
                select(Notification.appointment_id).where(
                    Notification.user_id == user_id,
                    Notification.kind == "reminder",
                    Notification.appointment_id.in_(
                        [appointment.id for appointment, _p, _s in upcoming]
                    ),
                )
            )
        ).scalars().all()
        already = {int(value) for value in existing if value is not None}

        created = 0
        for appointment, _patient, service in upcoming:
            if appointment.id in already:
                continue
            patient_name = _patient.full_name
            title, body = reminder_copy(
                appointment, patient_name, service.name
            )
            _add_notification(
                db,
                user_id=user_id,
                kind="reminder",
                title=title,
                body=body,
                appointment_id=appointment.id,
            )
            created += 1
        if created:
            await db.commit()
        return created
    except Exception:
        await db.rollback()
        logger.exception("Failed to synthesize appointment reminders")
        return 0
