"""Final-response construction, error mapping and turn-ending helpers."""

import json
import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.appointment_selection import (
    normalize_text,
)
from app.agent.messages import _append_message
from app.agent.state import AgentState
from app.agent_tools.schemas import AgentToolError
from app.errors import ERROR_CATALOG
from app.models.appointment import Appointment
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.utils.date_utils import gregorian_to_jalali
from app.utils.persian import to_persian_digits

logger = logging.getLogger("dental_agent.agent")


def _catalog_error(code: str) -> AgentToolError:
    definition = ERROR_CATALOG[code]
    return AgentToolError(code=definition.code, message=definition.message, details={})


def _provider_failure_code(exc: Exception) -> str | None:
    """Map provider SDK failures to a safe, retryable catalog code.

    The exception text is never surfaced. Provider throttling and transient
    connectivity/5xx failures are distinguished from application bugs so the
    UI can offer a retry instead of a generic internal-error reply.
    """
    current: BaseException | None = exc
    for _ in range(4):
        if current is None:
            break
        name = type(current).__name__.lower()
        status: int | None = None
        for candidate in (current, getattr(current, "response", None)):
            value = getattr(candidate, "status_code", None)
            if isinstance(value, int):
                status = value
                break
        if "ratelimit" in name or status == 429:
            return "AGENT_PROVIDER_RATE_LIMITED"
        if (
            "timeout" in name
            or "connection" in name
            or (status is not None and status >= 500)
        ):
            return "AGENT_PROVIDER_UNAVAILABLE"
        current = current.__cause__ or current.__context__
    return None


_WRITE_TOOL_NAMES = {
    "book_appointment",
    "cancel_appointment",
    "reschedule_appointment",
}


def _mentions_internal_appointment_id(text: str, appointment_id: int) -> bool:
    """Whether a user-facing string repeats the internal appointment id."""
    normalized = normalize_text(text)
    return bool(
        re.search(
            rf"(?<![\d/]){appointment_id}(?![\d/])",
            normalized,
        )
    )


async def _write_success_message(
    db: AsyncSession, state: AgentState
) -> str | None:
    """Build a descriptive success message without internal appointment ids.

    All names and times come from the committed database row. If that row is
    unavailable, use a generic no-id message rather than echoing the tool
    payload. Returns None for failed or non-write tools.
    """
    name = state.get("last_tool_name")
    result = state.get("last_tool_result")
    if name not in _WRITE_TOOL_NAMES:
        return None
    if not isinstance(result, dict) or not result.get("ok"):
        return None
    data = result.get("data")
    if not isinstance(data, dict):
        return None

    # The row id is carried in trusted graph state, never in the model-visible
    # tool payload.
    appointment_id = state.get("last_internal_appointment_id")
    appointment = None
    if isinstance(appointment_id, int):
        try:
            appointment = await db.get(Appointment, appointment_id)
        except Exception as exc:  # noqa: BLE001 - messaging must not fail
            logger.warning(
                "Could not load committed appointment for success message (%s)",
                type(exc).__name__,
            )
    if appointment is not None:
        try:
            appointment_date, appointment_time = (
                to_persian_digits(part)
                for part in gregorian_to_jalali(appointment.appointment_time)
            )
            doctor = await db.get(Doctor, appointment.doctor_id)
            service = await db.get(DentalService, appointment.service_id)
            doctor_name = (
                doctor.full_name if doctor is not None else "پزشک ثبت‌شده"
            )
            service_name = (
                service.name if service is not None else "خدمت ثبت‌شده"
            )
        except Exception as exc:  # noqa: BLE001 - messaging must not fail
            logger.warning(
                "Could not describe committed appointment (%s)",
                type(exc).__name__,
            )
        else:
            if name == "book_appointment":
                return (
                    f"نوبت «{service_name}» با {doctor_name} در تاریخ "
                    f"{appointment_date} ساعت {appointment_time} ثبت شد."
                )
            if name == "cancel_appointment":
                return (
                    f"نوبت «{service_name}» با {doctor_name} در تاریخ "
                    f"{appointment_date} ساعت {appointment_time} لغو شد."
                )
            return (
                f"نوبت «{service_name}» با {doctor_name} به تاریخ "
                f"{appointment_date} ساعت {appointment_time} منتقل شد."
            )

    # No database row is available (for example it disappeared after a
    # committed write). Keep the fallback success explicit but id-free.
    if name == "book_appointment":
        appointment_time = data.get("appointment_time")
        if appointment_time:
            return f"نوبت برای {to_persian_digits(appointment_time)} ثبت شد."
        return "نوبت با موفقیت ثبت شد."
    if name == "cancel_appointment":
        return "نوبت با موفقیت لغو شد."
    appointment_time = data.get("appointment_time")
    if appointment_time:
        return f"نوبت به {to_persian_digits(appointment_time)} منتقل شد."
    return "نوبت با موفقیت جابه‌جا شد."


async def _successful_write_fallback(
    db: AsyncSession, state: AgentState
) -> str | None:
    """Describe a committed write when only the final LLM phrasing failed.

    The fallback is derived exclusively from the successful tool result and
    committed database row. It never runs the tool again and returns None for
    failed or non-write tools, so an error cannot be reported as a success.
    """
    return await _write_success_message(db, state)


async def _sanitize_write_final_response(
    db: AsyncSession,
    state: AgentState,
    response: str,
) -> str:
    """Replace an LLM reply that leaked the internal appointment id."""
    name = state.get("last_tool_name")
    result = state.get("last_tool_result")
    if name not in _WRITE_TOOL_NAMES:
        return response
    if not isinstance(result, dict) or not result.get("ok"):
        return response
    data = result.get("data")
    if not isinstance(data, dict):
        return response
    appointment_id = state.get("last_internal_appointment_id")
    if not isinstance(appointment_id, int):
        return response
    if not _mentions_internal_appointment_id(response, appointment_id):
        return response
    safe = await _write_success_message(db, state)
    return safe or "عملیات با موفقیت انجام شد."


def _tool_message(
    *,
    call_id: str,
    name: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "name": name,
        "content": json.dumps(result, ensure_ascii=False),
    }


def _finish_rejected_confirmation(state: AgentState) -> dict[str, Any]:
    messages = list(state.get("messages", []))
    for call in state.get("pending_tool_calls", []):
        messages.append(
            _tool_message(
                call_id=call["tool_call_id"],
                name=call["tool_name"],
                result={
                    "ok": False,
                    "confirmation": {"status": "rejected"},
                },
            )
        )
    response = "درخواست انجام نشد."
    messages.append({"role": "assistant", "content": response})
    return {
        "confirmation_required": False,
        "confirmation_token": None,
        "pending_action": None,
        "pending_tool_calls": [],
        "selected_tool": None,
        "selected_tool_arguments": {},
        "selected_tool_call_id": None,
        "last_internal_appointment_id": None,
        "route": "finish",
        "final_response": response,
        "messages": messages,
    }


def _finish_clarification(state: AgentState, response: str) -> dict[str, Any]:
    """End a turn with a clarification and no usable write confirmation."""
    messages = list(state.get("messages", []))
    for call in state.get("pending_tool_calls", []):
        messages.append(
            _tool_message(
                call_id=call["tool_call_id"],
                name=call["tool_name"],
                result={
                    "ok": False,
                    "data": None,
                    "error": {
                        "code": "APPOINTMENT_SELECTION_REQUIRED",
                        "message": response,
                        "details": {},
                    },
                },
            )
        )
    messages.append({"role": "assistant", "content": response})
    return {
        "confirmation_required": False,
        "confirmation_token": None,
        "confirmation_prompt": None,
        "confirmation_status": "not_required",
        "pending_action": None,
        "pending_tool_calls": [],
        "selected_tool": None,
        "selected_tool_arguments": {},
        "selected_tool_call_id": None,
        "last_tool_result": None,
        "last_tool_error": None,
        "last_tool_name": None,
        "last_internal_appointment_id": None,
        "route": "finish",
        "final_response": response,
        "messages": messages,
    }


def _finish_error(state: AgentState, code: str) -> dict[str, Any]:
    """End the turn with a catalogued Persian message and no pending write."""
    error = _catalog_error(code)
    result = {"ok": False, "data": None, "error": error.model_dump(mode="json")}
    return {
        "confirmation_required": False,
        "confirmation_token": None,
        "confirmation_status": "not_required",
        "pending_action": None,
        "pending_tool_calls": [],
        "selected_tool": None,
        "selected_tool_arguments": {},
        "selected_tool_call_id": None,
        "last_tool_result": result,
        "last_tool_error": error,
        "last_tool_name": None,
        "last_internal_appointment_id": None,
        "route": "finish",
        "final_response": error.message,
        "messages": _append_message(state, "assistant", error.message),
    }


def _finish_step_limit(state: AgentState, steps: int) -> dict[str, Any]:
    response = (
        "درخواست بیش از حد پیچیده شد و برای جلوگیری از اجرای ناقص متوقف شد. "
        "لطفاً آن را کوتاه‌تر و مشخص‌تر بنویسید یا یک خدمت را انتخاب کنید."
    )
    return {
        "confirmation_required": False,
        "confirmation_token": None,
        "confirmation_status": "not_required",
        "pending_action": None,
        "pending_tool_calls": [],
        "selected_tool": None,
        "selected_tool_arguments": {},
        "selected_tool_call_id": None,
        "last_internal_appointment_id": None,
        "route": "finish",
        "final_response": response,
        "messages": _append_message(state, "assistant", response),
        "step_count": steps,
    }
