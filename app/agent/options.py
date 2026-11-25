"""Server-side numeric option selection for agent conversations.

When a turn ends with selectable options (services, doctors, free slots, or
proposed appointments), the conversation stores that set server-side inside
``AgentConversation.options_kind/options_payload``. The next answered message
may be a bare numeric reference («2», «۲», «گزینه ۲», «گزینه دوم»); the server
maps it against exactly the options that were displayed — Persian and Arabic
digit variants are normalized first, and the option number is parsed from the
message instead of concatenated.

The resolution never trusts a model-produced mapping: the selected item is
turned into a deterministic, data-carrying instruction for the model, and the
final action still runs through the normal tool authorization and (for writes)
the confirmation gate. An out-of-range number replays the active options as a
clarification instead of guessing.
"""

from __future__ import annotations

import re
from typing import Any

_DIGIT_TRANSLATION = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)

_ORDINAL_WORDS = {
    "اول": 1,
    "دوم": 2,
    "سوم": 3,
    "چهارم": 4,
    "پنجم": 5,
    "ششم": 6,
    "هفتم": 7,
    "هشتم": 8,
    "نهم": 9,
    "دهم": 10,
}

# Fillers a natural selection sentence may add around the option term.
_FILLER_TOKENS = {
    "من",
    "می",
    "میخواهم",
    "خواهم",
    "انتخاب",
    "میکنم",
    "میکنم.",
    "ارسال",
    "کنم",
    "کن.",
    "کن",
    "لطفا",
    "لازم",
    "دارم",
    "را",
    "این",
    "بده",
    "بزن",
}
# Cardinals accepted only AFTER an option keyword (گزینه دو), never bare.
_OPTION_TERM_CARDINALS = {
    "یک": 1,
    "دو": 2,
    "سه": 3,
    "چهار": 4,
    "پنج": 5,
    "شش": 6,
    "هفت": 7,
    "هشت": 8,
    "نُه": 9,
    "نو": 9,
    "ده": 10,
}
# A message containing any decision verb is not a bare option selection even
# if it also contains a number.
_COMMAND_WORDS = (
    "رزرو",
    "لغو",
    "جابجا",
    "نگاه",
    "پیدا",
    "دنبال",
    "بگیر",
    "حذف",
    "ثبت",
    "تأیید",
    "تایید",
    "بله",
    "خیر",
)

_TRIM_CHARS = ".،!؟?:؛;،٫-()«»'\"]\u200c"

_VALID_KINDS = frozenset(
    {"service", "doctor", "slot_time", "appointment", "patient"}
)

number_pattern = re.compile(r"^\d{1,2}$")


def normalize_digits(text: str) -> str:
    """Normalize Persian/Arabic digits and YWJ/Kaf variants to ASCII."""
    return (
        text.translate(_DIGIT_TRANSLATION)
        .replace("ي", "ی")
        .replace("ك", "ک")
        .replace("\u0654", "")  # hamza above: گزینهٔ -> گزینه
        .replace("\u200f", "")
        .replace("\u200e", "")
        .strip()
    )


def parse_option_index(message: str) -> int | None:
    """Return a 1-based option index, or None when the text is not one.

    Accepted forms (digit-normalized, whitespace-insensitive):
    - bare ``2`` / ``۲`` / ``02`` (optionally with a trailing ``.`` or ``،``)
    - ``گزینه 2`` / ``گزینه دوم`` / ``شماره 2`` / ``عدد 2``
    - the same forms wrapped in polite filler words (``گزینه دوم را
      انتخاب می‌کنم``), as long as no decision verb is present.

    «نوبت 2» is deliberately NOT included: phrases like «نوبت دوم را لغو
    کن» or «نوبت دوم چیست» name an appointment row, not a listed option.
    """
    normalized = normalize_digits(message)
    if not normalized:
        return None
    lower = normalized.lower()

    # Reject anything that carries another (including confirmation) intent;
    # only genuinely bare selections are hijacked server-side.
    for word in _COMMAND_WORDS:
        if word in lower:
            return None

    cleaned = lower.replace("\u200c", " ")
    cleaned = cleaned.strip(_TRIM_CHARS)
    tokens = [token.strip(_TRIM_CHARS) for token in cleaned.split()]
    tokens = [token for token in tokens if token]
    if not tokens:
        return None

    # Drop leading/trailing polite fillers only.
    while tokens and tokens[0] in _FILLER_TOKENS:
        tokens.pop(0)
    while tokens and tokens[-1] in _FILLER_TOKENS:
        tokens.pop()

    if not tokens:
        return None

    if len(tokens) == 1:
        token = tokens[0]
        if number_pattern.fullmatch(token):
            return _validated_index(int(token))
        if token in _ORDINAL_WORDS:
            return _ordinal_index(token)
        return None

    if tokens and tokens[0].rstrip(_TRIM_CHARS) in {"گزینه", "شماره", "عدد"}:
        rest = tokens[1:]
        if len(rest) == 1:
            candidate = rest[0].strip(_TRIM_CHARS)
            if number_pattern.fullmatch(candidate):
                return _validated_index(int(candidate))
            if candidate in _ORDINAL_WORDS:
                return _ordinal_index(candidate)
            if candidate in _OPTION_TERM_CARDINALS:
                return _validated_index(_OPTION_TERM_CARDINALS[candidate])
    return None


def _validated_index(value: int) -> int | None:
    return value if 1 <= value <= 99 else None


def _ordinal_index(word: str) -> int:
    return _ORDINAL_WORDS[word]


def _nearest_items(result_data: Any) -> list[dict[str, Any]]:
    """Appointment option items from a find_nearest_appointments payload."""
    if not isinstance(result_data, dict):
        return []
    appointments = result_data.get("appointments")
    if not isinstance(appointments, list) or not appointments:
        return []
    items = []
    for item in appointments[:10]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("service_name") or "").strip()
        doctor = str(item.get("doctor_name") or "").strip()
        date = str(item.get("appointment_date") or "").strip()
        time = str(item.get("appointment_time") or "").strip()
        if not (name and doctor and date and time):
            continue
        items.append(
            {
                "kind": "appointment",
                "label": name,
                "doctor_name": doctor,
                "doctor_id": _as_int(item.get("doctor_id")),
                "service_id": _as_int(item.get("service_id")),
                "appointment_date": date,
                "appointment_time": time,
            }
        )
    return items


def _slot_items(result_data: Any) -> list[dict[str, Any]]:
    """Appointment option items from a find_available_slots payload.

    Names are not part of that tool's payload; the router fills them from
    the database before the set is stored or rendered.
    """
    if not isinstance(result_data, dict):
        return []
    slots = result_data.get("available_slots")
    if not isinstance(slots, list) or not slots:
        return []
    doctor_id = _as_int(result_data.get("doctor_id"))
    service_id = _as_int(result_data.get("service_id"))
    date = str(result_data.get("appointment_date") or "").strip()
    if not doctor_id or not service_id or not date:
        return []
    items = []
    seen: set[str] = set()
    for slot in slots:
        text = str(slot or "").strip()
        clock = text[:5] if ":" in text[:5] else (text.split("T")[-1][:5] if text else "")
        if not clock or ":" not in clock or clock in seen:
            continue
        seen.add(clock)
        items.append(
            {
                "kind": "appointment",
                "label": "",
                "doctor_name": "",
                "doctor_id": doctor_id,
                "service_id": service_id,
                "appointment_date": date,
                "appointment_time": clock,
            }
        )
    return items


def build_merged_slot_options(
    tool_events: list[tuple[str, Any]],
    *,
    limit: int = 10,
) -> tuple[str, dict[str, Any]] | None:
    """Merge every slot-bearing read result of a turn into one option set.

    A turn may check slots for several doctors (one find_available_slots
    call each). Storing only the last call's result — the old behaviour —
    made a numeric pick resolve against a different list than the one the
    user was shown, so «۱» could book another doctor/service/time than the
    first displayed option. Merging all of the turn's slot results, in
    call order and deduplicated, keeps the stored set aligned with what
    the turn actually offered.
    """
    items: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any, Any, Any]] = set()
    for name, result in tool_events:
        if not isinstance(result, dict) or not result.get("ok"):
            continue
        if name == "find_nearest_appointments":
            candidates = _nearest_items(result.get("data"))
        elif name == "find_available_slots":
            candidates = _slot_items(result.get("data"))
        else:
            continue
        for item in candidates:
            key = (
                item.get("doctor_id"),
                item.get("service_id"),
                item.get("appointment_date"),
                item.get("appointment_time"),
            )
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    if not items:
        return None
    return ("appointment", {"items": items[:limit]})


def anchor_requested_time(
    kind: str, payload: dict[str, Any], requested_times: set[str]
) -> dict[str, Any]:
    """Move the slot the user explicitly asked for to the front of a set.

    When the request names exactly one clock time («فردا ساعت ۱۰») and that
    time is among the offered slots, a bare «۱» must mean that slot — not
    whatever happens to be first in the day's raw slot order.
    """
    if len(requested_times) != 1 or not isinstance(payload, dict):
        return payload
    target = next(iter(requested_times))
    items = payload.get("items")
    if not isinstance(items, list):
        return payload
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        clock = str(
            item.get("appointment_time") or item.get("time") or ""
        ).strip()[:5]
        if clock == target:
            if index == 0:
                return payload
            reordered = [item, *items[:index], *items[index + 1 :]]
            return {**payload, "items": reordered}
    return payload


def build_active_options(
    last_tool_name: str | None,
    last_tool_result: Any,
    *,
    doctor_service_context: dict[int, int] | None = None,
) -> tuple[str, dict[str, Any]] | None:
    """Convert the last successful read-tool result into a selectable set.

    Only validated tool output is used; model text is never parsed. Returns
    ``(kind, payload)`` with the smallest stable data set the client needs to
    render cards and the server needs to resolve a later numeric reply.
    ``last_tool_result`` is the model-visible ``AgentToolResult`` dump:
    ``{"ok": ..., "data": <payload>, "error": ...}`` where ``data`` is a bare
    list for the service/doctor listing tools.

    ``doctor_service_context`` optionally maps ``doctor_id -> service_id`` so
    a picked doctor can propose slots for the service in play without a
    second search roundtrip.
    """
    if not isinstance(last_tool_result, dict) or not last_tool_result.get("ok"):
        return None
    result_data = last_tool_result.get("data")

    if last_tool_name == "find_nearest_appointments":
        items = _nearest_items(result_data)
        return ("appointment", {"items": items}) if items else None

    if last_tool_name == "find_available_slots":
        if not isinstance(result_data, dict):
            return None
        slots = result_data.get("available_slots")
        if not isinstance(slots, list) or not slots:
            return None
        doctor_id = _as_int(result_data.get("doctor_id"))
        service_id = _as_int(result_data.get("service_id"))
        date = str(result_data.get("appointment_date") or "").strip()
        times: list[str] = []
        for slot in slots:
            text = str(slot or "").strip()
            clock = text[:5] if ":" in text[:5] else (text.split("T")[-1][:5] if text else "")
            if clock and ":" in clock and clock not in times:
                times.append(clock)
        if not times or not doctor_id or not service_id or not date:
            return None
        payload = {
            "doctor_id": doctor_id,
            "service_id": service_id,
            "appointment_date": date,
            "items": [{"kind": "slot_time", "time": value} for value in times],
        }
        return ("slot_time", payload)

    if last_tool_name == "search_dental_services":
        services = result_data if isinstance(result_data, list) else None
        if not services:
            return None
        items = []
        for item in services[:10]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            items.append(
                {
                    "kind": "service",
                    "label": name,
                    "service_id": _as_int(item.get("id")),
                    "description": (item.get("description") or "").strip() or None,
                }
            )
        return ("service", {"items": items}) if items else None

    if last_tool_name == "find_doctors_for_service":
        doctors = result_data if isinstance(result_data, list) else None
        if not doctors:
            return None
        context = doctor_service_context or {}
        items = []
        for item in doctors[:10]:
            if not isinstance(item, dict):
                continue
            doctor_name = str(item.get("full_name") or "").strip()
            if not doctor_name:
                continue
            payload_item = {
                "kind": "doctor",
                "label": doctor_name,
                "doctor_id": _as_int(item.get("id")),
                "specialty": (item.get("specialty") or "").strip() or None,
            }
            mapped = context.get(_as_int(item.get("id")))
            if mapped is not None:
                payload_item["service_id"] = mapped
            items.append(payload_item)
        return ("doctor", {"items": items}) if items else None

    return None


def _as_int(value: Any) -> int | None:
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def resolve_option(
    kind: str | None,
    payload: dict[str, Any] | None,
    index: int,
) -> dict[str, Any] | None:
    """Return the selected item of the active option set, or None."""
    if kind not in _VALID_KINDS:
        return None
    if not isinstance(payload, dict):
        return None
    items = payload.get("items")
    if not isinstance(items, list):
        return None
    if not 1 <= index <= len(items):
        return None
    item = items[index - 1]
    return item if isinstance(item, dict) else None


def build_patient_options(
    patients: list[dict[str, Any]],
    *,
    pending_selection: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]] | None:
    """Build server-owned ``patient`` option cards for a multi-record account."""
    items = []
    for patient in patients[:20]:
        patient_id = _as_int(patient.get("id"))
        label = str(patient.get("full_name") or "").strip()
        if patient_id is None or not label:
            continue
        items.append(
            {
                "kind": "patient",
                "label": label,
                "patient_id": patient_id,
                "is_account_holder": bool(patient.get("is_account_holder")),
            }
        )
    if not items:
        return None
    payload: dict[str, Any] = {"items": items}
    if pending_selection:
        payload["pending_selection"] = pending_selection
    return ("patient", payload)


def booking_args_for_option(
    kind: str,
    payload: dict[str, Any],
    item: dict[str, Any],
    patient_id: int,
) -> dict[str, Any] | None:
    """Turn a selected slot/appointment card into deterministic book args."""
    if kind == "slot_time":
        date = str(payload.get("appointment_date") or "").strip()
        clock = str(item.get("time") or "").strip()[:5]
        doctor_id = _as_int(payload.get("doctor_id"))
        service_id = _as_int(payload.get("service_id"))
    elif kind == "appointment":
        date = str(item.get("appointment_date") or "").strip()
        clock = str(item.get("appointment_time") or "").strip()[:5]
        doctor_id = _as_int(item.get("doctor_id"))
        service_id = _as_int(item.get("service_id"))
    else:
        return None
    if not (date and clock and doctor_id and service_id and patient_id):
        return None
    return {
        "patient_id": patient_id,
        "doctor_id": doctor_id,
        "service_id": service_id,
        "appointment_date": date,
        "appointment_time": clock,
    }


def build_selection_instruction(
    kind: str, payload: dict[str, Any], item: dict[str, Any]
) -> str:
    """Build a deterministic, data-carrying instruction for the model.

    Ids included here come from validated tool output stored server-side, so
    the model can pass them straight into the next allowlisted tool call.
    """
    if kind == "service":
        service_id = item.get("service_id")
        id_part = f" (service_id {service_id})" if service_id else ""
        return (
            f"خدمت «{item.get('label')}»{id_part} را انتخاب می‌کنم؛ لطفاً "
            "نزدیک‌ترین زمان‌های آزاد این خدمت را برای من بررسی کن."
        )
    if kind == "doctor":
        service_id = item.get("service_id")
        if service_id:
            return (
                f"برای service_id {service_id} پزشک «{item.get('label')}» "
                f"(doctor_id {item.get('doctor_id')}) را انتخاب می‌کنم؛ "
                "لطفاً نزدیک‌ترین زمان‌های آزاد این خدمت را برای من بررسی کن."
            )
        return (
            f"پزشک «{item.get('label')}» (doctor_id {item.get('doctor_id')}) "
            "را انتخاب می‌کنم؛ لطفاً خدمت مناسب و نزدیک‌ترین زمان‌های آزاد "
            "او را برای من بررسی کن."
        )
    if kind == "slot_time":
        return (
            f"برای service_id {payload.get('service_id')} و doctor_id "
            f"{payload.get('doctor_id')} در تاریخ "
            f"{payload.get('appointment_date')} ساعت {item.get('time')} "
            "نوبت رزرو کن."
        )
    if kind == "patient":
        return (
            f"بیمار «{item.get('label')}» را برای این نوبت انتخاب می‌کنم. "
            "لطفاً درخواست قبلی را برای همین بیمار ادامه بده."
        )
    service_id = item.get("service_id")
    doctor_id = item.get("doctor_id")
    id_part = " "
    if service_id or doctor_id:
        id_part = (
            f" (service_id {service_id}, doctor_id {doctor_id}) "
        )
    return (
        f"نوبت «{item.get('label')}» با پزشک «{item.get('doctor_name')}» در "
        f"تاریخ {item.get('appointment_date')} ساعت "
        f"{item.get('appointment_time')}{id_part}را برای رزرو پیش ببر."
    )


def option_slots_hint(kind: str | None, payload: dict[str, Any] | None) -> bool:
    """Whether stored options can satisfy a numeric reply."""
    return kind in _VALID_KINDS and isinstance(payload, dict)


def render_options_message(kind: str, payload: dict[str, Any]) -> str:
    """Re-render the stored options as a numbered Persian list."""
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        return "گزینهٔ معتبری برای انتخاب در دسترس نیست؛ لطفاً پیشنهادها را دوباره از من بخواهید."
    header = "گزینه‌های فعال فعلی این گفتگو:"
    lines = []
    for position, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        if kind == "service":
            description = item.get("description")
            line = f"{position}. خدمت «{item.get('label')}»"
            if description:
                line += f": {str(description)[:60]}"
        elif kind == "doctor":
            specialty = item.get("specialty")
            line = f"{position}. پزشک «{item.get('label')}»"
            if specialty:
                line += f" ({specialty})"
        elif kind == "slot_time":
            line = (
                f"{position}. ساعت {item.get('time')} در تاریخ "
                f"{payload.get('appointment_date')}"
            )
        elif kind == "patient":
            suffix = " (خودم)" if item.get("is_account_holder") else ""
            line = f"{position}. بیمار «{item.get('label')}»{suffix}"
        else:
            line = (
                f"{position}. «{item.get('label')}» با "
                f"{item.get('doctor_name')} در {item.get('appointment_date')} "
                f"ساعت {item.get('appointment_time')}"
            )
        lines.append(line)
    body = "\n".join(lines) if lines else "گزینه‌ای برای نمایش وجود ندارد."
    return (
        f"{header}\n{body}\n\n"
        "لطفاً شمارهٔ یکی از گزینه‌های بالا یا جزئیات آن را بفرستید."
    )


def valid_option_count(kind: str | None, payload: dict[str, Any] | None) -> int:
    if not option_slots_hint(kind, payload):
        return 0
    items = payload.get("items") if isinstance(payload, dict) else None
    return len(items) if isinstance(items, list) else 0


def list_option_items(
    kind: str | None, payload: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Return the dict items of an active option set, in display order."""
    if not option_slots_hint(kind, payload):
        return []
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]
