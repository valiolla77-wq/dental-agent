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
# Explicit rejection used when every appointment matching the request is in
# the past: a past appointment can neither be cancelled nor rescheduled, and
# the user must hear that directly instead of a "which one?" list.
PAST_TARGET_MESSAGE = (
    "نوبت موردنظر شما در گذشته است و لغو یا جابه‌جایی نوبت گذشته ممکن "
    "نیست. اگر مایل باشید، می‌توانم نزدیک‌ترین نوبت جدید را برایتان پیدا "
    "کنم."
)
PAST_DESTINATION_MESSAGE = (
    "نمی‌توانم نوبت را به گذشته منتقل کنم؛ تاریخ و ساعت جدید در گذشته "
    "است. لطفاً روز و ساعت دیگری در آینده بگویید."
)
BOOKING_MISMATCH_MESSAGE = (
    "مشخصات نوبت انتخاب‌شده با درخواست شما هم‌خوانی ندارد. لطفاً خدمت، "
    "پزشک، تاریخ یا ساعت موردنظرتان را دوباره مشخص کنید."
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


# Persian possessive suffixes that may attach directly to a service name or
# one of its tokens: «ترمیمم» (my filling), «ترمیمت», «ترمیمش»,
# «ترمیممان», «ترمیم‌تان», «ترمیمشان». Longer forms first so the
# alternation prefers «مان» over «م». A suffix joined with a ZWNJ already
# matches without this — normalize_text turns the ZWNJ into a space, which
# is a word boundary — but a directly attached suffix defeats the ``(?!\w)``
# boundary, so the token never matched (eval B02: the service filter never
# engaged and every multi-appointment request came back AMBIGUOUS).
_POSSESSIVE_SUFFIXES = ("مان", "تان", "شان", "م", "ت", "ش")


def _name_pattern(token: str, *, allow_possessive: bool) -> str:
    """Word-boundary pattern for one name token.

    With ``allow_possessive`` the token may carry a directly attached
    possessive suffix. Nothing else about the boundary changes: other
    continuations (``ترمیمی``, ``ترمیمات``) still do not match.
    """
    pattern = rf"(?<!\w){re.escape(token)}"
    if allow_possessive:
        suffix = "|".join(_POSSESSIVE_SUFFIXES)
        pattern += rf"(?:{suffix})?"
    return pattern + r"(?!\w)"


def _name_matches(
    text: str,
    name: str,
    generic_tokens: set[str],
    *,
    allow_possessive: bool = False,
) -> bool:
    normalized_name = " ".join(normalize_text(name).split())
    if normalized_name and re.search(
        _name_pattern(normalized_name, allow_possessive=allow_possessive),
        text,
    ):
        return True
    return any(
        re.search(
            _name_pattern(token, allow_possessive=allow_possessive), text
        )
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
    if "دیروز" in compact:
        dates.add(current - timedelta(days=1))
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


def explicit_clock_times(text: str) -> set[str]:
    """Public wrapper: the ``HH:MM`` clock times a text names explicitly."""
    return _clock_times(text)


# Persian weekday names, Monday=0 ... Sunday=6, matching
# ``datetime.weekday()`` and ``prompts._WEEKDAYS``. ``normalize_text``
# turns a ZWNJ into a space, so «سه‌شنبه» arrives as «سه شنبه» while
# «پنجشنبه» keeps its joined form; both spellings are listed.
_WEEKDAY_NUMBERS = {
    "یکشنبه": 6,
    "سه شنبه": 1,
    "چهارشنبه": 2,
    "پنج شنبه": 3,
    "پنجشنبه": 3,
    "دوشنبه": 0,
    "شنبه": 5,
    "جمعه": 4,
}
_WEEKDAY_PATTERN = re.compile(
    r"(?<!\w)("
    + "|".join(re.escape(name) for name in _WEEKDAY_NUMBERS)
    + r")(?!\w)"
)


def _weekday_dates(text: str, now: datetime | None) -> set[date]:
    """The date of a named weekday («شنبهٔ آینده», «جمعه»)."""
    current = clinic_now(now).date()
    compact = " ".join(normalize_text(text).split()).replace("ٔ", "")
    match = _WEEKDAY_PATTERN.search(compact)
    if match is None:
        return set()
    target = _WEEKDAY_NUMBERS[match.group(1)]
    days_ahead = (target - current.weekday()) % 7
    if days_ahead == 0 and ("آینده" in compact or "بعدی" in compact):
        # «شنبهٔ آینده» on a Saturday means next week, not today.
        days_ahead = 7
    return {current + timedelta(days=days_ahead)}


def parse_reschedule_destination(
    text: str, now: datetime | None
) -> tuple[str, str, datetime] | None:
    """Parse a reschedule destination clause into Jalali date, time, datetime.

    ``text`` must be the destination clause only (see
    ``confirmation_text._destination_text``): the source appointment's
    own date/time must never leak into it, or «فردا» in B05 would be
    read as the destination. Returns ``(jalali_date, "HH:MM",
    gregorian_datetime)`` with Latin digits, or None when the clause
    names no single date or no single time — the caller then falls back
    to asking instead of guessing a slot. The datetime is a naive
    Tehran wall-clock value, comparable with ``clinic_now(now)``.
    """
    dates = (
        _explicit_dates(text)
        | _relative_dates(text, now)
        | _weekday_dates(text, now)
    )
    times = _clock_times(text)
    if len(dates) != 1 or len(times) != 1:
        return None
    day = next(iter(dates))
    clock = next(iter(times))
    hour, minute = (int(part) for part in clock.split(":"))
    jalali = jdatetime.date.fromgregorian(date=day)
    return (
        f"{jalali.year}/{jalali.month:02d}/{jalali.day:02d}",
        clock,
        datetime(day.year, day.month, day.day, hour, minute),
    )


async def _scheduled_for_patients(
    db: AsyncSession, patient_ids: list[int]
) -> list[Appointment]:
    result = await db.execute(
        select(Appointment)
        .where(
            Appointment.patient_id.in_(patient_ids),
            Appointment.status == "scheduled",
        )
        .order_by(Appointment.appointment_time)
    )
    return list(result.scalars().all())


async def _scheduled_for_patient(
    db: AsyncSession, patient_id: int
) -> list[Appointment]:
    return await _scheduled_for_patients(db, [patient_id])


async def _scheduled_all(db: AsyncSession) -> list[Appointment]:
    """Staff-only fallback when no patient scope was supplied.

    The caller must be authorized for the write action before this is used.
    Ambiguity still requires clarification, so this never picks a row silently.
    """
    result = await db.execute(
        select(Appointment)
        .where(Appointment.status == "scheduled")
        .order_by(Appointment.appointment_time)
    )
    return list(result.scalars().all())


async def _match_candidates(
    db: AsyncSession,
    candidates: list[Appointment],
    user_text: str,
    now: datetime | None,
) -> list[Appointment]:
    """Filter DB rows by the explicit criteria in the user's request."""
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
            text,
            service.name,
            _GENERIC_SERVICE_TOKENS,
            allow_possessive=True,
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
    return matched


async def resolve_appointment_target(
    db: AsyncSession,
    *,
    appointment_id: int | None,
    user_text: str,
    patient_id: int | None = None,
    patient_ids: list[int] | None = None,
    now: datetime | None = None,
) -> AppointmentSelection:
    """Resolve a cancel/reschedule target from database facts.

    ``appointment_id`` is an optional staff/model hint, not an authority. For
    patient callers the graph passes every linked patient id, so only records
    owned by that account are candidates and any foreign hint is rejected.
    With no id, the target is selected only when the user's explicit criteria
    identify exactly one row. Missing or multiple matches return a
    clarification and issue no confirmation.

    A missing or non-scheduled explicit target is returned as-is so the
    confirmation/description code can raise its precise catalogued error.
    """
    scope_ids = [int(value) for value in (patient_ids or [])]
    if patient_id is not None and int(patient_id) not in scope_ids:
        scope_ids.append(int(patient_id))

    target = (
        await db.get(Appointment, appointment_id)
        if isinstance(appointment_id, int)
        else None
    )
    if appointment_id is not None and target is None:
        return AppointmentSelection(None)
    if target is not None and target.status != "scheduled":
        return AppointmentSelection(target)
    if (
        target is not None
        and scope_ids
        and int(target.patient_id) not in scope_ids
    ):
        # A supplied id outside the authorized patient scope is never used.
        return AppointmentSelection(None, NO_MATCHING_SELECTION_MESSAGE)

    if not scope_ids and target is not None:
        scope_ids = [int(target.patient_id)]

    candidates = (
        await _scheduled_for_patients(db, scope_ids)
        if scope_ids
        else await _scheduled_all(db)
    )

    if not candidates:
        return AppointmentSelection(None, NO_MATCHING_SELECTION_MESSAGE)

    # Always run the criteria filter, even when only one row is scheduled.
    # "امروز"/"فردا" must never silently retarget an existing appointment to a
    # different day; an unmatched date yields a clarification instead.
    matched = await _match_candidates(db, candidates, user_text, now)

    if target is not None:
        if len(matched) == 1 and matched[0].id == target.id:
            return AppointmentSelection(target)
        if not matched:
            return AppointmentSelection(None, NO_MATCHING_SELECTION_MESSAGE)
        if len(matched) == 1:
            # The hint points at a different appointment than the explicit
            # request identifies. Never silently override the request.
            return AppointmentSelection(None, MISMATCHED_SELECTION_MESSAGE)
        return AppointmentSelection(None, AMBIGUOUS_SELECTION_MESSAGE)

    # Past-appointment handling for model/patient proposals (no trusted id).
    # A past appointment can neither be cancelled nor rescheduled:
    # - when the request explicitly points at a past day and every match is
    #   in the past, reject explicitly instead of listing "which one?";
    # - when the request names no date, past rows never make an otherwise
    #   unique future target ambiguous.
    if matched:
        now_dt = clinic_now(now)
        explicit_dates = _relative_dates(user_text, now) | _explicit_dates(
            user_text
        )
        future = [
            item for item in matched if item.appointment_time >= now_dt
        ]
        if not future:
            if explicit_dates and max(explicit_dates) <= now_dt.date():
                return AppointmentSelection(None, PAST_TARGET_MESSAGE)
        elif len(future) == 1 and not explicit_dates:
            matched = future

    if len(matched) == 1:
        return AppointmentSelection(matched[0])
    if not matched:
        return AppointmentSelection(None, NO_MATCHING_SELECTION_MESSAGE)
    return AppointmentSelection(None, AMBIGUOUS_SELECTION_MESSAGE)


def _assistant_mentions_slot(
    assistant_text: str, jalali_date: str, clock: str
) -> bool:
    """Whether the model's last reply itself offered this date/time.

    A user who accepted an alternative the assistant proposed in words
    («۱۰ پر است، ۹:۳۰ چطور؟» — «باشه») must not be blocked by the guard, so a
    booked slot the assistant explicitly mentioned is treated as accepted.
    """
    if not assistant_text:
        return False
    normalized = normalize_text(assistant_text)
    if clock and clock in _clock_times(assistant_text):
        return True
    return bool(jalali_date) and jalali_date in normalized


async def booking_criteria_mismatch(
    db: AsyncSession,
    *,
    arguments: dict,
    user_texts: list[str],
    now: datetime | None = None,
    last_assistant_text: str = "",
) -> str | None:
    """Check a proposed booking against the user's explicit criteria.

    The model proposes ``book_appointment`` arguments; before a confirmation
    is issued, the service, doctor, date and time the user actually named
    (in any of their messages) are compared with the proposal. A definite
    contradiction returns ``BOOKING_MISMATCH_MESSAGE`` so the turn ends with
    a clarification instead of a confirmation for the wrong slot. Criteria
    the user never named are not checked, and a date/time the assistant
    itself offered in its last reply counts as user-accepted.

    Only used for model-proposed bookings; server-resolved option picks are
    already bound to the displayed option set and skip this check.
    """
    texts = [text for text in user_texts if text and text.strip()]
    if not texts:
        return None

    doctors = list(
        (
            await db.execute(
                select(Doctor).where(Doctor.is_active.is_(True))
            )
        )
        .scalars()
        .all()
    )
    services = list(
        (
            await db.execute(
                select(DentalService).where(
                    DentalService.is_active.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )

    doctor_ids: set[int] = set()
    service_ids: set[int] = set()
    times: set[str] = set()
    dates: set[date] = set()
    for text in texts:
        compact = " ".join(normalize_text(text).split())
        for doctor in doctors:
            if _name_matches(compact, doctor.full_name, _GENERIC_DOCTOR_TOKENS):
                doctor_ids.add(doctor.id)
        for service in services:
            if _name_matches(
                compact,
                service.name,
                _GENERIC_SERVICE_TOKENS,
                allow_possessive=True,
            ):
                service_ids.add(service.id)
        times |= _clock_times(text)
        dates |= _relative_dates(text, now) | _explicit_dates(text)

    doctor_id = arguments.get("doctor_id")
    if (
        doctor_ids
        and isinstance(doctor_id, int)
        and doctor_id not in doctor_ids
    ):
        return BOOKING_MISMATCH_MESSAGE
    service_id = arguments.get("service_id")
    if (
        service_ids
        and isinstance(service_id, int)
        and service_id not in service_ids
    ):
        return BOOKING_MISMATCH_MESSAGE

    jalali_date = str(arguments.get("appointment_date") or "").strip()
    clock = str(arguments.get("appointment_time") or "").strip()[:5]
    offered = _assistant_mentions_slot(last_assistant_text, jalali_date, clock)
    if times and clock and clock not in times and not offered:
        return BOOKING_MISMATCH_MESSAGE
    if dates and jalali_date:
        try:
            year, month, day = (
                int(part)
                for part in jalali_date.replace("-", "/").split("/")
            )
            proposed = jdatetime.date(year, month, day).togregorian()
        except (ValueError, OverflowError):
            proposed = None
        if proposed is not None and proposed not in dates and not offered:
            return BOOKING_MISMATCH_MESSAGE
    return None
