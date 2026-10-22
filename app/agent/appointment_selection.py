"""Server-side disambiguation for appointment cancel/reschedule requests.

The language model proposes an ``appointment_id``. Before that proposal can
become a confirmation, the server checks the patient's scheduled appointments
against the explicit criteria in the user's request (doctor, service, Jalali or
Gregorian date, clock time, and a few relative date words). If more than one
appointment matches, no target is selected and the caller must ask the user for
a narrower description.

This module deliberately does not expose appointment ids to the user. It also
does not mutate appointments; it is a read-only guard used before confirmation
issuance and before any write tool can run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import jdatetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.services.appointment_service import clinic_now

_DIGIT_TRANSLATION = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)

_GENERIC_DOCTOR_TOKENS = {
    "دکتر",
    "پزشک",
    "دندانپزشک",
    "دندانپزشکی",
    "خانم",
    "آقا",
}
_GENERIC_SERVICE_TOKENS = {
    "خدمت",
    "نوبت",
    "دندان",
    "دندانپزشکی",
    "پزشک",
    "دکتر",
    "اولیه",
}

# Both messages are intentionally short and contain no appointment ids or
# details of other appointments.
AMBIGUOUS_SELECTION_MESSAGE = (
    "برای این درخواست چند نوبت با مشخصات مشابه وجود دارد. لطفاً پزشک، خدمت، "
    "تاریخ یا ساعت نوبت موردنظر را دقیق‌تر مشخص کنید."
)
NO_MATCHING_SELECTION_MESSAGE = (
    "نوبتی با مشخصات ذکرشده پیدا نشد. لطفاً پزشک، خدمت، تاریخ یا ساعت نوبت "
    "موردنظر را مشخص کنید."
)
MISMATCHED_SELECTION_MESSAGE = (
    "نوبت انتخاب‌شده با مشخصات درخواست شما هم‌خوانی ندارد. لطفاً پزشک، خدمت، "
    "تاریخ یا ساعت نوبت موردنظر را مشخص کنید."
)


@dataclass(frozen=True)
class AppointmentSelection:
    """Resolved target, or a clarification that must end the turn."""

    appointment: Appointment | None
    clarification: str | None = None


def normalize_text(value: str) -> str:
    """Normalize Persian/Arabic digits and common character variants."""
    return (
        value.translate(_DIGIT_TRANSLATION)
        .replace("ي", "ی")
        .replace("ك", "ک")
        .replace("\u200c", " ")
        .replace("\u200f", "")
        .replace("\u200e", "")
        .lower()
    )


def _name_tokens(value: str, generic_tokens: set[str]) -> list[str]:
    normalized = normalize_text(value)
    return [
        token
        for token in re.findall(r"[^\W\d_]+", normalized, flags=re.UNICODE)
        if len(token) >= 3 and token not in generic_tokens
    ]


def _name_matches(text: str, name: str, generic_tokens: set[str]) -> bool:
    normalized_name = " ".join(normalize_text(name).split())
    if normalized_name and re.search(
        rf"(?<!\w){re.escape(normalized_name)}(?!\w)", text
    ):
        return True
    return any(
        re.search(rf"(?<!\w){re.escape(token)}(?!\w)", text)
        for token in _name_tokens(name, generic_tokens)
    )


def _relative_dates(text: str, now: datetime | None) -> set[date]:
    current = clinic_now(now).date()
    dates: set[date] = set()
    compact = " ".join(normalize_text(text).split())
    if "پس فردا" in compact or "پسفردا" in compact:
        dates.add(current + timedelta(days=2))
    elif "فردا" in compact:
        dates.add(current + timedelta(days=1))
    if "امروز" in compact:
        dates.add(current)
    return dates


def _explicit_dates(text: str) -> set[date]:
    text = normalize_text(text)
    dates: set[date] = set()
    for year, month, day in re.findall(
        r"(?<!\d)(\d{4})[/-](\d{1,2})[/-](\d{1,2})(?!\d)", text
    ):
        try:
            y, m, d = int(year), int(month), int(day)
            if 1900 <= y <= 2100:
                dates.add(jdatetime.date.fromgregorian(date=date(y, m, d)).togregorian())
            else:
                dates.add(jdatetime.date(y, m, d).togregorian())
        except (ValueError, OverflowError):
            continue
    return dates


def _clock_times(text: str) -> set[str]:
    text = normalize_text(text)
    times = {
        f"{int(hour):02d}:{minute}"
        for hour, minute in re.findall(
            r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", text
        )
    }
    # "ساعت ۹" is common colloquial shorthand for 09:00. Do not treat the
    # colon form above as a second match.
    for hour in re.findall(
        r"ساعت\s*([01]?\d|2[0-3])(?!\s*:)(?!\d)", text
    ):
        times.add(f"{int(hour):02d}:00")
    return times


async def _scheduled_for_patient(
    db: AsyncSession, patient_id: int
) -> list[Appointment]:
    result = await db.execute(
        select(Appointment)
        .where(
            Appointment.patient_id == patient_id,
            Appointment.status == "scheduled",
        )
        .order_by(Appointment.appointment_time)
    )
    return list(result.scalars().all())


async def resolve_appointment_target(
    db: AsyncSession,
    *,
    appointment_id: int | None,
    user_text: str,
    now: datetime | None = None,
) -> AppointmentSelection:
    """Resolve an agent-proposed target against the request's explicit criteria.

    A missing or non-scheduled target is returned as-is so the existing
    confirmation/description code can raise its precise catalogued error. A
    scheduled target is only approved when it is the single scheduled
    appointment for that patient that matches the request. Otherwise the
    caller receives a clarification string and must issue no confirmation.
    """
    if not isinstance(appointment_id, int):
        return AppointmentSelection(None)

    target = await db.get(Appointment, appointment_id)
    if target is None or target.status != "scheduled":
        return AppointmentSelection(target)

    candidates = await _scheduled_for_patient(db, target.patient_id)
    if len(candidates) <= 1:
        return AppointmentSelection(target)

    text = " ".join(normalize_text(user_text).split())
    dates = _relative_dates(text, now) | _explicit_dates(text)
    times = _clock_times(text)

    matched = candidates

    if dates:
        matched = [
            item
            for item in matched
            if item.appointment_time.date() in dates
        ]
    if times:
        matched = [
            item
            for item in matched
            if item.appointment_time.strftime("%H:%M") in times
        ]

    # Match explicit doctor/service names only against names read from the DB.
    selected_doctors: set[int] = set()
    selected_services: set[int] = set()
    for item in candidates:
        doctor = await db.get(Doctor, item.doctor_id)
        service = await db.get(DentalService, item.service_id)
        if doctor is not None and _name_matches(
            text, doctor.full_name, _GENERIC_DOCTOR_TOKENS
        ):
            selected_doctors.add(item.doctor_id)
        if service is not None and _name_matches(
            text, service.name, _GENERIC_SERVICE_TOKENS
        ):
            selected_services.add(item.service_id)

    if selected_doctors:
        matched = [
            item for item in matched if item.doctor_id in selected_doctors
        ]
    if selected_services:
        matched = [
            item for item in matched if item.service_id in selected_services
        ]

    if len(matched) == 1 and matched[0].id == target.id:
        return AppointmentSelection(target)

    if not matched:
        return AppointmentSelection(None, NO_MATCHING_SELECTION_MESSAGE)
    if len(matched) == 1:
        # The model proposed a different appointment than the one the explicit
        # request identifies. Never silently override its choice.
        return AppointmentSelection(None, MISMATCHED_SELECTION_MESSAGE)
    return AppointmentSelection(None, AMBIGUOUS_SELECTION_MESSAGE)
