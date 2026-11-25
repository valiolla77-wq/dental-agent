"""Deterministic stall recovery for single-message agent turns.

The decision model sometimes ends a turn with words instead of the tool
chain the request needs: it fetches the patient's appointments and then
asks a free-text «آیا مطمئنید؟» instead of proposing the write, promises
«پیدا می‌کنم» after identifying a service without ever asking for slots,
or rejects a reschedule before looking at any data. Prompt rules alone did
not reliably prevent these stalls, so the graph detects the shape of a
stalled turn — a text-only finish after (or without) specific read tools,
for a message carrying a clear cancel/reschedule/booking intent — and
re-asks the model once per stall stage with a server directive appended
as a system message.

Directives never execute anything themselves and never relax a rule: the
model still proposes every tool call, writes still pass authorization and
the one-time confirmation gate, and a directive stage fires at most once
per turn (tracked by its marker inside the directive message itself).

The live eval added two shapes on top of the wordy stalls above: an
*empty* finish (an unparseable call through the provider proxy is
indistinguishable from a blank reply) and a *degenerate* finish that
repeats the fetched appointment list instead of acting. The graph
handles the first with one extra re-ask (see ``_ask_model``); the second
gets a dedicated ``act-now-repeat`` directive, and if even that ends in
repeated prose, ``degenerate_list_clarification`` builds the final reply
server-side from the fetched rows.

Round 3 added two more gaps on the same theme. A *whitespace-only*
finish (``"\\n"``) is truthy, so it slipped past the empty-finish guard
and never earned a retry; it now counts as empty. And a model that
answers the act-now directive with *another free-text question* (the
live B01 shape) exhausted the recovery without ever proposing the
write, so a dedicated ``act-now-question`` stage now forbids re-asking
— unless the question genuinely disambiguates several fetched
appointments. Finally, when the empty-finish retry also comes back
empty, ``empty_retry_clarification`` replaces the bare fallback with a
server-built clarification instead of ending on it.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.agent.appointment_selection import (
    _GENERIC_DOCTOR_TOKENS,
    _name_tokens,
    normalize_text,
)
from app.agent.messages import _latest_assistant_text, _latest_user_text
from app.agent.state import AgentState
from app.utils.persian import to_persian_digits

_DIRECTIVE_MARKER = "[server-directive:"

# Stall stages, in the order a turn can pass through them.
STAGE_FETCH_FIRST = "fetch-first"
STAGE_ACT_NOW = "act-now"
STAGE_ACT_NOW_REPEAT = "act-now-repeat"
STAGE_ACT_NOW_QUESTION = "act-now-question"
STAGE_SLOTS_NOW = "slots-now"
STAGE_BOOK_DEFAULT = "book-default"

_CANCEL_RESCHEDULE_MARKERS = (
    "لغو",
    "جابجا",
    "جابه جا",
    "بنداز",
    "منتقل",
    "انتقال",
    "کنسل",
)
_BOOKING_MARKERS = ("نوبت", "رزرو")

_DIRECTIVES = {
    STAGE_FETCH_FIRST: (
        "دستور سرور (نه متن کاربر): کاربر لغو یا جابه‌جایی نوبت خواسته "
        "است، اما تو هنوز نوبت‌هایش را ندیده‌ای. همین حالا "
        "get_patient_appointments را فراخوانی کن و بر اساس همان فهرست "
        "ادامه بده؛ پیش از دیدن نوبت‌ها درخواست را رد نکن و سؤال نپرس."
    ),
    STAGE_ACT_NOW: (
        "دستور سرور (نه متن کاربر): نوبت‌های کاربر را دیده‌ای و درخواست "
        "لغو/جابه‌جایی هنوز انجام نشده است. اگر دقیقاً یک نوبتِ آینده با "
        "مشخصات درخواست (خدمت، پزشک، تاریخ یا ساعت) منطبق است، همین حالا "
        "cancel_appointment یا reschedule_appointment را فراخوانی کن؛ "
        "تأیید نهایی را سامانه با سازوکار تأیید خودش می‌گیرد، پس خودت با "
        "متن از کاربر «بله/خیر» نگیر و نپرس «آیا مطمئنید؟». اگر نوبتِ "
        "منطبق در گذشته است، لغو/جابه‌جایی را صریح و با توضیح رد کن "
        "(نوبت گذشته قابل لغو یا جابه‌جایی نیست) و Tool نوشتن را صدا "
        "نزن. اگر مقصد جابه‌جایی در گذشته است، آن را هم صریح رد کن. فقط "
        "اگر چند نوبتِ آینده با مشخصات مشابه وجود دارد، یک سؤال روشن با "
        "ذکر پزشک، تاریخ و ساعت هرکدام بپرس."
    ),
    STAGE_ACT_NOW_REPEAT: (
        "دستور سرور (نه متن کاربر): پاسخ قبلی‌ات فهرست نوبت‌ها را چند "
        "بار تکرار کرد و درخواست لغو/جابه‌جایی هنوز انجام نشده است. "
        "فهرست را دوباره ننویس و هیچ جمله‌ای را تکرار نکن. اگر دقیقاً "
        "یک نوبتِ آینده با مشخصات درخواست منطبق است، همین حالا "
        "cancel_appointment یا reschedule_appointment را فراخوانی کن. "
        "اگر چند نوبتِ آیندهٔ منطبق وجود دارد، فقط یک سؤال کوتاه بپرس "
        "که پزشک، تاریخ و ساعت هرکدام را نام ببرد. اگر نوبتِ منطبق در "
        "گذشته است، ردّ صریح و کوتاه بنویس."
    ),
    STAGE_ACT_NOW_QUESTION: (
        "دستور سرور (نه متن کاربر): تو همین حالا از کاربر پرسیده‌ای و "
        "او هنوز جواب نداده است؛ همان سؤال را دوباره نپرس و با متن "
        "«آیا مطمئنید؟» از او تأیید نگیر. اگر دقیقاً یک نوبتِ آینده "
        "با مشخصات درخواست (خدمت، پزشک، تاریخ یا ساعت) منطبق است، "
        "همین حالا cancel_appointment یا reschedule_appointment را "
        "فراخوانی کن؛ تأیید نهایی را سامانه با سازوکار تأیید خودش "
        "می‌گیرد. فقط اگر چند نوبتِ آینده با مشخصات مشابه وجود دارد، "
        "یک سؤال کوتاه بپرس که پزشک، تاریخ و ساعت هرکدام را نام ببرد. "
        "اگر نوبتِ منطبق در گذشته است، لغو/جابه‌جایی را صریح و با "
        "توضیح رد کن و Tool نوشتن را صدا نزن."
    ),
    STAGE_SLOTS_NOW: (
        "دستور سرور (نه متن کاربر): خدمت را پیدا کرده‌ای، اما هنوز هیچ "
        "ساعت آزادی نشان نداده‌ای. همین حالا با service_id همان خدمت "
        "find_nearest_appointments را فراخوانی کن و ساعت‌های واقعی "
        "برگشتی را نشان بده؛ اگر کاربر روز مشخصی نام برده است، به‌جای آن "
        "پزشکان خدمت را بگیر و find_available_slots را برای دقیقاً همان "
        "روز صدا بزن. پاسخ را با وعدهٔ «پیدا می‌کنم» تمام نکن."
    ),
    STAGE_BOOK_DEFAULT: (
        "دستور سرور (نه متن کاربر): کاربر نوبت می‌خواهد و تو هنوز هیچ "
        "Toolای صدا نزده‌ای. اگر خدمت یا شکایتی نام نبرده است، خدمت "
        "پیش‌فرض «معاینه اولیه دندانپزشکی» است: اول "
        "search_dental_services را صدا بزن و بلافاصله با service_id آن "
        "find_nearest_appointments را فراخوانی کن و نزدیک‌ترین ساعت‌های "
        "واقعی را پیشنهاد بده؛ نپرس «برای چه خدمتی؟». اشاره به بیمه یا "
        "هزینه مانع رزرو نیست و دربارهٔ آن چیزی نساز."
    ),
}


def _used_stages(state: AgentState) -> set[str]:
    """Stages whose directive already fired earlier in this turn."""
    stages: set[str] = set()
    for item in state.get("messages", []):
        if item.get("role") != "system":
            continue
        content = item.get("content")
        if not isinstance(content, str) or _DIRECTIVE_MARKER not in content:
            continue
        tail = content.split(_DIRECTIVE_MARKER, 1)[1]
        stage = tail.split("]", 1)[0].strip()
        if stage:
            stages.add(stage)
    return stages


def _turn_tool_names(state: AgentState) -> set[str]:
    """Names of tools that ran successfully since the latest user message."""
    names: set[str] = set()
    for item in reversed(state.get("messages", [])):
        if item.get("role") == "user":
            break
        if item.get("role") != "tool":
            continue
        name = item.get("name")
        if not isinstance(name, str):
            continue
        content = item.get("content")
        ok = True
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict) and parsed.get("ok") is False:
                ok = False
        if ok:
            names.add(name)
    return names


def _turn_had_tool_error(state: AgentState) -> bool:
    """Whether any tool call since the latest user message failed.

    A failed call (patient selection required, validation, authorization)
    is a legitimate reason for the model to end the turn with a question
    or an explanation, so such turns are never treated as stalls.
    """
    for item in reversed(state.get("messages", [])):
        if item.get("role") == "user":
            break
        if item.get("role") != "tool":
            continue
        content = item.get("content")
        if not isinstance(content, str):
            continue
        try:
            parsed = json.loads(content)
        except ValueError:
            continue
        if isinstance(parsed, dict) and parsed.get("ok") is False:
            return True
    return False


def _repeated_lines(text: str) -> bool:
    """Whether a reply repeats the same substantive line at least twice.

    Degenerate provider completions loop a block (in eval B02 the fetched
    appointment list came back ~5.5 times). A legitimate reply may list
    several appointments, but each line appears once, so repeated
    substantive lines are a reliable degeneration signal.
    """
    lines = [
        " ".join(normalize_text(line).split()) for line in text.splitlines()
    ]
    substantive = [line for line in lines if len(line) >= 8]
    return len(substantive) >= 4 and len(set(substantive)) < len(substantive)


def _fetched_appointment_items(state: AgentState) -> list[dict[str, Any]]:
    """Items of this turn's latest successful ``get_patient_appointments``.

    The tool payload carries model-visible facts only (doctor, service,
    Jalali date/time, status — never internal ids), so rebuilding a
    clarification from it discloses nothing the turn had not already
    been shown.
    """
    for item in reversed(state.get("messages", [])):
        if item.get("role") == "user":
            break
        if item.get("role") != "tool":
            continue
        if item.get("name") != "get_patient_appointments":
            continue
        content = item.get("content")
        if not isinstance(content, str):
            return []
        try:
            parsed = json.loads(content)
        except ValueError:
            return []
        if not isinstance(parsed, dict) or parsed.get("ok") is not True:
            return []
        data = parsed.get("data")
        if not isinstance(data, list):
            return []
        return [entry for entry in data if isinstance(entry, dict)]
    return []


def _fetched_appointment_lines(state: AgentState) -> list[str]:
    """One deduped line per fetched appointment, Persian digits, no ids.

    Shared by the server-built clarifications: the tool payload carries
    model-visible facts only (doctor, service, Jalali date/time, status —
    never internal ids), so rebuilding a clarification from it discloses
    nothing the turn had not already been shown.
    """
    items = _fetched_appointment_items(state)
    lines: list[str] = []
    seen: set[tuple[str, str, str, str]] = set()
    for entry in items:
        key = (
            str(entry.get("doctor_name", "")),
            str(entry.get("service_name", "")),
            str(entry.get("appointment_date", "")),
            str(entry.get("appointment_time", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        lines.append(
            f"- نوبت «{key[1]}» با {key[0]} در تاریخ "
            f"{to_persian_digits(key[2])} ساعت {to_persian_digits(key[3])}"
        )
    return lines


def _mentioned_doctor_names(
    text: str, items: list[dict[str, Any]]
) -> set[str]:
    """Distinct fetched doctor names the text names (full name or token)."""
    normalized = " ".join(normalize_text(text).split())
    mentioned: set[str] = set()
    for entry in items:
        name = " ".join(normalize_text(str(entry.get("doctor_name", ""))).split())
        if not name or name in mentioned:
            continue
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", normalized):
            mentioned.add(name)
            continue
        if any(
            re.search(rf"(?<!\w){re.escape(token)}(?!\w)", normalized)
            for token in _name_tokens(name, _GENERIC_DOCTOR_TOKENS)
        ):
            mentioned.add(name)
    return mentioned


def _mentioned_dates(text: str, items: list[dict[str, Any]]) -> set[str]:
    """Distinct fetched Jalali dates the text names (digits normalized)."""
    normalized = " ".join(normalize_text(text).split())
    return {
        str(entry.get("appointment_date", ""))
        for entry in items
        if str(entry.get("appointment_date", ""))
        and str(entry.get("appointment_date", "")) in normalized
    }


def _is_disambiguation_question(text: str, state: AgentState) -> bool:
    """Whether a question names two or more fetched appointments.

    A legitimate disambiguation question lists several appointments so the
    user can pick one — it names at least two doctors, or at least two
    distinct dates from the fetched rows. A yes/no question about a single
    appointment («آیا می‌خواهید این نوبت را لغو کنید؟») names at most one
    and is a stall, not a disambiguation.
    """
    items = _fetched_appointment_items(state)
    if not items:
        return False
    if len(_mentioned_doctor_names(text, items)) >= 2:
        return True
    return len(_mentioned_dates(text, items)) >= 2


def _is_question_stall(text: str, state: AgentState) -> bool:
    """Whether a reply is a free-text question that stalls the turn.

    A question that disambiguates several fetched appointments is
    legitimate and must be left alone; any other question after the
    act-now recovery — typically a yes/no «آیا مطمئنید؟» about one
    appointment — is the B01 stall shape.
    """
    normalized = " ".join(normalize_text(text).split())
    if "؟" not in normalized and "?" not in normalized:
        return False
    return not _is_disambiguation_question(text, state)


def degenerate_list_clarification(
    state: AgentState, final_text: str
) -> str | None:
    """Server-built clarification replacing a degenerate list reply.

    Returns a text only for the exact eval-B02 shape: a cancel/reschedule
    turn whose appointments were fetched, whose act-now recovery already
    fired, and whose final reply still repeats the appointment list back
    instead of acting or asking. The clarification is rebuilt from the
    fetched rows (each shown once, Persian digits) and asks the user to
    name the appointment — the model's prose is never surfaced.
    """
    if not _repeated_lines(final_text):
        return None
    user_text = _latest_user_text(state)
    if not user_text or _turn_had_tool_error(state):
        return None
    normalized = " ".join(normalize_text(user_text).split())
    if not any(marker in normalized for marker in _CANCEL_RESCHEDULE_MARKERS):
        return None
    if STAGE_ACT_NOW not in _used_stages(state):
        return None
    lines = _fetched_appointment_lines(state)
    if not lines:
        return None
    return "\n".join(
        [
            "برای این درخواست چند نوبت در فهرست شما هست و باید مشخص شود "
            "کدام‌یک مدنظرتان است. لطفاً پزشک، تاریخ یا ساعت نوبت موردنظر "
            "را مشخص کنید:"
        ]
        + lines
    )


def empty_retry_clarification(state: AgentState) -> str | None:
    """Server-built clarification after a failed empty-finish retry.

    Called only when the extra re-ask for an empty finish also came back
    empty or unusable (see ``_ask_model``): the bare «متوجه درخواست
    نشدم» fallback must never be the last word after a failed retry.
    For a cancel/reschedule turn whose appointments were fetched, the
    clarification presents them once and asks the user to name the
    appointment; without fetched rows it asks for the identifying
    details; for any other intent it names the available actions.
    """
    if _turn_had_tool_error(state):
        return None
    user_text = _latest_user_text(state)
    if not user_text:
        return None
    normalized = " ".join(normalize_text(user_text).split())
    if any(marker in normalized for marker in _CANCEL_RESCHEDULE_MARKERS):
        lines = _fetched_appointment_lines(state)
        if lines:
            return "\n".join(
                [
                    "پاسخ به درخواست شما آماده نشد. نوبت‌های شما این‌هاست؛ "
                    "لطفاً پزشک، تاریخ یا ساعت نوبت موردنظر را مشخص کنید:"
                ]
                + lines
            )
        return (
            "پاسخ به درخواست شما آماده نشد. برای لغو یا جابه‌جایی نوبت، "
            "لطفاً پزشک، تاریخ یا ساعت نوبت موردنظر را مشخص کنید تا نوبت "
            "درست را پیدا کنم."
        )
    return (
        "درخواست شما را به‌درستی دریافت نکردم. لطفاً بگویید می‌خواهید "
        "نوبت بگیرید، نوبت را لغو کنید یا نوبت را جابه‌جا کنید؟"
    )


def stall_directive(
    state: AgentState, *, patient_bound: bool
) -> tuple[str, str] | None:
    """Return ``(stage, directive_message)`` when this turn looks stalled.

    Called only when the model finished with plain text. A turn that
    already executed the relevant write, or one whose request carries no
    matching intent, is never nudged.
    """
    user_text = _latest_user_text(state)
    if not user_text:
        return None
    if _turn_had_tool_error(state):
        return None
    normalized = " ".join(normalize_text(user_text).split())
    used = _used_stages(state)
    tools = _turn_tool_names(state)

    if any(marker in normalized for marker in _CANCEL_RESCHEDULE_MARKERS):
        if (
            "get_patient_appointments" not in tools
            and STAGE_FETCH_FIRST not in used
        ):
            return STAGE_FETCH_FIRST, (
                f"{_DIRECTIVE_MARKER}{STAGE_FETCH_FIRST}] "
                f"{_DIRECTIVES[STAGE_FETCH_FIRST]}"
            )
        if (
            STAGE_ACT_NOW not in used
            and "cancel_appointment" not in tools
            and "reschedule_appointment" not in tools
        ):
            return STAGE_ACT_NOW, (
                f"{_DIRECTIVE_MARKER}{STAGE_ACT_NOW}] "
                f"{_DIRECTIVES[STAGE_ACT_NOW]}"
            )
        if (
            STAGE_ACT_NOW in used
            and STAGE_ACT_NOW_REPEAT not in used
            and "get_patient_appointments" in tools
            and "cancel_appointment" not in tools
            and "reschedule_appointment" not in tools
            and _repeated_lines(_latest_assistant_text(state))
        ):
            # The act-now re-ask was answered with the fetched list
            # repeated back (a degenerate completion), not with a call
            # or a real question. One last directive names that failure
            # explicitly; if it also ends in repeated prose, the graph
            # replaces the reply with a server-built clarification.
            return STAGE_ACT_NOW_REPEAT, (
                f"{_DIRECTIVE_MARKER}{STAGE_ACT_NOW_REPEAT}] "
                f"{_DIRECTIVES[STAGE_ACT_NOW_REPEAT]}"
            )
        if (
            STAGE_ACT_NOW in used
            and STAGE_ACT_NOW_QUESTION not in used
            and "get_patient_appointments" in tools
            and "cancel_appointment" not in tools
            and "reschedule_appointment" not in tools
            and _is_question_stall(_latest_assistant_text(state), state)
        ):
            # The act-now re-ask was answered with another free-text
            # question (the live B01 shape: a yes/no «آیا می‌خواهید…؟»
            # about one appointment) instead of the write. One more
            # directive forbids re-asking and demands the call; a
            # genuine disambiguation question naming several fetched
            # appointments never reaches this branch.
            return STAGE_ACT_NOW_QUESTION, (
                f"{_DIRECTIVE_MARKER}{STAGE_ACT_NOW_QUESTION}] "
                f"{_DIRECTIVES[STAGE_ACT_NOW_QUESTION]}"
            )
        return None

    if patient_bound and any(
        marker in normalized for marker in _BOOKING_MARKERS
    ):
        if (
            "search_dental_services" in tools
            and "find_nearest_appointments" not in tools
            and "find_available_slots" not in tools
            and STAGE_SLOTS_NOW not in used
        ):
            return STAGE_SLOTS_NOW, (
                f"{_DIRECTIVE_MARKER}{STAGE_SLOTS_NOW}] "
                f"{_DIRECTIVES[STAGE_SLOTS_NOW]}"
            )
        if not tools and STAGE_BOOK_DEFAULT not in used:
            return STAGE_BOOK_DEFAULT, (
                f"{_DIRECTIVE_MARKER}{STAGE_BOOK_DEFAULT}] "
                f"{_DIRECTIVES[STAGE_BOOK_DEFAULT]}"
            )
    return None
