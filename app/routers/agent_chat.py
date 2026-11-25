"""Authenticated chat endpoint for the LangGraph dental assistant.

Conversation turns are persisted server-side per ``(user_id, session_id)``:
the database is the authoritative history, never the client or localStorage.
Session ownership is always the server-side pair; a foreign ``session_id``
cannot name another user's conversation or a pending write.

The last turn's selectable options (services, doctors, free slots, proposed
appointments) are stored with the conversation, so a later bare numeric reply
(«2», «۲», «گزینه دوم») resolves deterministically against exactly what was
displayed — even after a page reload.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import agent_graph, create_initial_state
from app.agent.appointment_selection import explicit_clock_times
from app.agent.confirmations import confirmation_store
from app.agent.graph import AGENT_RECURSION_LIMIT, safe_tool_call_for_history
from app.agent.llm import ToolCallingChatModel, create_chat_model, load_llm_config
from app.agent.options import (
    anchor_requested_time,
    booking_args_for_option,
    build_active_options,
    build_merged_slot_options,
    build_patient_options,
    build_selection_instruction,
    list_option_items,
    option_slots_hint,
    parse_option_index,
    render_options_message,
    resolve_option,
)
from app.agent_tools.schemas import NearestAppointmentsToolData
from app.auth.dependencies import chat_rate_limit, get_current_user
from app.auth.permissions import linked_patient_ids
from app.database import get_db
from app.errors import AppError
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.user import User
from app.services import chat_history, patient_service

logger = logging.getLogger("dental_agent.agent_chat")

router = APIRouter(
    prefix="/agent",
    tags=["Agent"],
)

_WRITE_TOOL_NAMES = {
    "book_appointment",
    "cancel_appointment",
    "reschedule_appointment",
}

_LAST_TOOL_CALL_SERVICE_ID = "find_doctors_for_service"


class ChatConfirmation(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    decision: Literal["approved", "rejected"]


class ChatHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    history: list[ChatHistoryMessage] = Field(default_factory=list, max_length=20)
    confirmation: ChatConfirmation | None = None


class ChatSuggestedAppointment(BaseModel):
    doctor_id: int
    doctor_name: str
    service_id: int
    service_name: str
    appointment_date: str
    appointment_time: str


class ChatOptionItem(BaseModel):
    """A selectable card of the conversation's active option set.

    ``index`` is the 1-based number the client sends (as «گزینه N») to pick
    it; resolution happens server-side against the persisted set.
    """

    index: int
    kind: Literal["service", "doctor", "slot_time", "appointment", "patient"]
    label: str
    patient_id: int | None = None
    is_account_holder: bool | None = None
    doctor_id: int | None = None
    doctor_name: str | None = None
    service_id: int | None = None
    service_name: str | None = None
    appointment_date: str | None = None
    appointment_time: str | None = None
    specialty: str | None = None
    description: str | None = None


class ChatConversation(BaseModel):
    session_id: str
    title: str | None = None
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class ChatMessageOut(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class ChatConversationDetail(ChatConversation):
    messages: list[ChatMessageOut] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str
    confirmation_required: bool
    confirmation_prompt: str | None = None
    confirmation_token: str | None = None
    suggested_appointments: list[ChatSuggestedAppointment] = Field(
        default_factory=list
    )
    # Stable, explicit name for clients that render structured slot cards.
    # ``suggested_appointments`` is kept for backwards compatibility.
    slots: list[ChatSuggestedAppointment] = Field(default_factory=list)
    # Selectable cards of the active option set of this turn.
    options: list[ChatOptionItem] = Field(default_factory=list)
    # Server-side flag: the patient account has no linked record yet, so the
    # client may show the in-chat base-info registration form.
    form_required: bool = False
    session_id: str
    conversation_title: str | None = None
    request_id: str | None = None


def get_chat_llm() -> ToolCallingChatModel:
    """Load the configured provider; fail with a catalogued error otherwise.

    Overridable via FastAPI dependency_overrides in tests.
    """
    try:
        settings = load_llm_config()
    except ValueError as exc:
        raise AppError("AGENT_PROVIDER_NOT_CONFIGURED") from exc
    try:
        return create_chat_model(settings)
    except ValueError as exc:
        raise AppError("AGENT_PROVIDER_NOT_CONFIGURED") from exc


def _suggested_appointments(result: dict) -> list[ChatSuggestedAppointment]:
    """Expose the last nearest-slot result as optional UI cards.

    Only validated, structured Tool output is surfaced; free-text model output
    is never parsed. This is additive response data and does not change booking
    or confirmation behavior.
    """
    if result.get("last_tool_name") != "find_nearest_appointments":
        return []
    raw_result = result.get("last_tool_result")
    if not isinstance(raw_result, dict) or not raw_result.get("ok"):
        return []
    raw_data = raw_result.get("data")
    if not isinstance(raw_data, dict):
        return []
    try:
        data = NearestAppointmentsToolData.model_validate(raw_data)
    except ValueError:
        return []
    return [
        ChatSuggestedAppointment(**item.model_dump())
        for item in data.appointments
    ]


def _options_response(
    kind: str | None, payload: dict[str, Any] | None
) -> list[ChatOptionItem]:
    """Build client cards for an option set (stored or freshly captured)."""
    if not option_slots_hint(kind, payload):
        return []
    options: list[ChatOptionItem] = []
    for index, item in enumerate(
        list_option_items(kind, payload), start=1
    ):
        option = ChatOptionItem(
            index=index,
            kind=kind,  # type: ignore[arg-type]
            label=str(item.get("label") or ""),
        )
        if kind == "slot_time":
            date = payload.get("appointment_date") if isinstance(payload, dict) else None
            option.appointment_date = date if isinstance(date, str) else None
            time = item.get("time")
            option.appointment_time = str(time) if time is not None else None
        elif kind == "service":
            description = item.get("description")
            option.description = (
                str(description) if description is not None else None
            )
        elif kind == "doctor":
            specialty = item.get("specialty")
            option.specialty = str(specialty) if specialty is not None else None
        elif kind == "patient":
            option.patient_id = _as_int(item.get("patient_id"))
            option.is_account_holder = bool(item.get("is_account_holder"))
        else:  # appointment
            doctor_name = item.get("doctor_name")
            option.doctor_name = (
                str(doctor_name) if doctor_name is not None else None
            )
            option.service_name = option.label
            date = item.get("appointment_date")
            option.appointment_date = date if isinstance(date, str) else None
            time = item.get("appointment_time")
            option.appointment_time = str(time) if time is not None else None
        option.doctor_id = _as_int(item.get("doctor_id"))
        option.service_id = _as_int(item.get("service_id"))
        options.append(option)
    return options


def _as_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _last_tool_call_service_id(result: dict) -> int | None:
    """Return the service_id from this turn's last sanitized doctor listing."""
    for message in reversed(result.get("messages") or []):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            if call.get("name") != _LAST_TOOL_CALL_SERVICE_ID:
                continue
            args = call.get("args")
            if not isinstance(args, dict):
                return None
            try:
                return int(args.get("service_id"))
            except (TypeError, ValueError):
                return None
    return None


_SLOT_TOOL_NAMES = {"find_available_slots", "find_nearest_appointments"}


def _turn_tool_events(result: dict) -> list[tuple[str, Any]]:
    """All tool results of this turn, in execution order.

    Read from the graph's tool messages (validated tool output only; the
    model's prose is never parsed).
    """
    events: list[tuple[str, Any]] = []
    for message in result.get("messages") or []:
        if not isinstance(message, dict) or message.get("role") != "tool":
            continue
        name = message.get("name")
        content = message.get("content")
        if not isinstance(name, str) or not isinstance(content, str):
            continue
        try:
            parsed = json.loads(content)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            events.append((name, parsed))
    return events


def _turn_active_options(
    result: dict,
    *,
    requested_times: set[str] | None = None,
) -> tuple[str | None, dict[str, Any] | None]:
    """Decide the conversation's active option set after this turn.

    A successful read listing becomes the new set; a write proposal or an
    executed write clears the previous set so a stale «گزینه ۲» can never
    select a removed slot.

    When the turn produced slot results from more than one call (e.g. the
    same day checked for two doctors), all of them are merged into a
    single appointment set: storing only the last call's slots made a
    numeric pick resolve against a different list than the one the user
    was shown. A single slot result keeps the historical per-tool shape.
    Either way, when the user's request names exactly one clock time and
    that time is offered, it is anchored to the front of the set so a
    bare «۱» means the slot the user actually asked for.
    """
    name = result.get("last_tool_name")
    if not isinstance(name, str) or name in _WRITE_TOOL_NAMES:
        return None, None
    times = requested_times or set()
    events = _turn_tool_events(result)
    slot_events = [event for event in events if event[0] in _SLOT_TOOL_NAMES]
    if len(slot_events) >= 2:
        merged = build_merged_slot_options(events)
        if merged is not None:
            kind, payload = merged
            return kind, anchor_requested_time(kind, payload, times)
    doctor_service_context: dict[int, int] = {}
    if name == "find_doctors_for_service":
        service_id = _last_tool_call_service_id(result)
        if service_id is not None:
            doctors = (result.get("last_tool_result") or {}).get("data")
            if isinstance(doctors, list):
                doctor_service_context = {
                    int(item.get("id")): service_id
                    for item in doctors
                    if isinstance(item, dict)
                    and isinstance(item.get("id"), int)
                }
    options = build_active_options(
        name,
        result.get("last_tool_result"),
        doctor_service_context=doctor_service_context,
    )
    if options is None:
        return None, None
    kind, payload = options
    return kind, anchor_requested_time(kind, payload, times)


async def _fill_appointment_option_names(
    db: AsyncSession, payload: dict[str, Any]
) -> None:
    """Fill doctor/service names on merged slot items from the database.

    find_available_slots results carry ids only; the merged appointment
    set needs display names, and they must come from database records —
    never from model text.
    """
    items = payload.get("items")
    if not isinstance(items, list):
        return
    doctor_ids = {
        item.get("doctor_id")
        for item in items
        if isinstance(item, dict) and isinstance(item.get("doctor_id"), int)
    }
    service_ids = {
        item.get("service_id")
        for item in items
        if isinstance(item, dict) and isinstance(item.get("service_id"), int)
    }
    doctors: dict[int, str] = {}
    services: dict[int, str] = {}
    if doctor_ids:
        rows = (
            await db.execute(select(Doctor).where(Doctor.id.in_(doctor_ids)))
        ).scalars()
        doctors = {row.id: row.full_name for row in rows}
    if service_ids:
        rows = (
            await db.execute(
                select(DentalService).where(DentalService.id.in_(service_ids))
            )
        ).scalars()
        services = {row.id: row.name for row in rows}
    for item in items:
        if not isinstance(item, dict):
            continue
        if not item.get("doctor_name"):
            item["doctor_name"] = doctors.get(item.get("doctor_id"), "")
        if not item.get("label"):
            item["label"] = services.get(item.get("service_id"), "")


def _tool_error_code(result: dict) -> str | None:
    """Read the stable error code from either graph error representation."""
    error = result.get("last_tool_error")
    if error is None:
        return None
    if isinstance(error, dict):
        return error.get("code")
    return getattr(error, "code", None)


async def _owned_patient_dicts(
    db: AsyncSession, user: User
) -> list[dict[str, Any]]:
    """Return all records owned by a patient account, primary first."""
    if user.role != "patient":
        return []
    ids = await linked_patient_ids(db, user)
    patients = []
    for patient_id in ids:
        patient = await patient_service.get_patient(db, patient_id)
        patients.append(
            {
                "id": patient.id,
                "full_name": patient.full_name,
                "is_account_holder": patient.is_account_holder,
            }
        )
    return patients


def _form_required(result: dict, actor: User) -> bool:
    """Kept for older clients; chat itself is registration-gated."""
    return _tool_error_code(result) == "PATIENT_ACCOUNT_NOT_LINKED"


def _recursion_fallback_reply() -> str:
    return (
        "درخواست بیش از حد پیچیده شد و برای جلوگیری از اجرای ناقص "
        "متوقف شد. لطفاً آن را کوتاه‌تر و مشخص‌تر بنویسید."
    )


@dataclass
class _TurnPlan:
    """What the deterministic pre-processing decided for this turn."""

    message: str
    requested_tool: str | None = None
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    selected_patient_id: int | None = None


async def _resolve_numeric_option(
    plan: _TurnPlan,
    *,
    db: AsyncSession,
    request: Request,
    payload: ChatRequest,
    conversation: Any,
    session_id: str,
    owned_patients: list[dict[str, Any]],
    owned_patient_ids: set[int],
    active_kind: str | None,
    active_payload: dict[str, Any] | None,
    active_count: int,
) -> ChatResponse | None:
    """Resolve a bare option number («۲») without involving the model.

    Returns a finished ``ChatResponse`` when the turn can be answered right
    away (patient prompt, re-shown options); otherwise ``None`` and ``plan``
    carries the rewritten message / forced tool call for the graph.
    """
    response_message = plan.message
    requested_tool = plan.requested_tool
    tool_arguments = plan.tool_arguments
    selected_patient_id = plan.selected_patient_id
    try:
        if payload.confirmation is None:
            candidate = parse_option_index(payload.message)
            if candidate is not None:
                item = resolve_option(active_kind, active_payload, candidate)
                if item is not None and active_kind == "patient":
                    chosen = _as_int(item.get("patient_id"))
                    if chosen in owned_patient_ids:
                        selected_patient_id = chosen
                        conversation.selected_patient_id = chosen
                        await db.commit()
                        pending = (
                            active_payload.get("pending_selection")
                            if isinstance(active_payload, dict)
                            else None
                        )
                        direct_args = None
                        if isinstance(pending, dict):
                            direct_args = booking_args_for_option(
                                str(pending.get("kind") or ""),
                                pending.get("payload")
                                if isinstance(pending.get("payload"), dict)
                                else {},
                                pending.get("item")
                                if isinstance(pending.get("item"), dict)
                                else {},
                                chosen,
                            )
                        if direct_args is not None:
                            requested_tool = "book_appointment"
                            tool_arguments = direct_args
                            response_message = (
                                f"نوبت برای بیمار «{item.get('label')}» "
                                "به‌صورت قطعی انتخاب شد."
                            )
                        else:
                            response_message = build_selection_instruction(
                                active_kind, active_payload, item
                            )
                elif item is not None and active_kind in {
                    "slot_time",
                    "appointment",
                }:
                    direct_args = booking_args_for_option(
                        active_kind,
                        active_payload,
                        item,
                        selected_patient_id or 0,
                    )
                    if selected_patient_id is None and len(owned_patients) > 1:
                        pending_kind, pending_payload = build_patient_options(
                            owned_patients,
                            pending_selection={
                                "kind": active_kind,
                                "payload": active_payload,
                                "item": item,
                            },
                        )
                        if pending_payload is not None:
                            prompt = "برای کدام بیمار این نوبت ثبت شود؟"
                            await chat_history.append_turn(
                                db,
                                conversation=conversation,
                                user_text=payload.message,
                                assistant_text=prompt,
                                assistant_available=True,
                            )
                            await chat_history.save_active_options(
                                db,
                                conversation=conversation,
                                kind=pending_kind,
                                payload=pending_payload,
                            )
                            return ChatResponse(
                                reply=prompt,
                                confirmation_required=False,
                                suggested_appointments=[],
                                slots=[],
                                options=_options_response(
                                    pending_kind, pending_payload
                                ),
                                session_id=session_id,
                                conversation_title=conversation.title,
                                request_id=getattr(
                                    request.state, "request_id", None
                                ),
                            )
                    if direct_args is not None:
                        requested_tool = "book_appointment"
                        tool_arguments = direct_args
                        response_message = (
                            "ثبت نوبت برای زمان انتخاب‌شده آغاز شد."
                        )
                    else:
                        response_message = (
                            "بیمار انتخاب‌شده معتبر نیست؛ لطفاً بیمار را دوباره "
                            "انتخاب کنید."
                        )
                elif item is not None:
                    response_message = build_selection_instruction(
                        active_kind, active_payload, item
                    )
                elif active_count:
                    # An out-of-range number is never handed to the model as a
                    # bare «۲»; re-show exactly the captured set instead.
                    enumeration = render_options_message(
                        active_kind, active_payload  # type: ignore[arg-type]
                    )
                    await chat_history.append_turn(
                        db,
                        conversation=conversation,
                        user_text=payload.message,
                        assistant_text=enumeration,
                        assistant_available=True,
                    )
                    return ChatResponse(
                        reply=enumeration,
                        confirmation_required=False,
                        suggested_appointments=[],
                        slots=[],
                        options=_options_response(active_kind, active_payload),
                        session_id=session_id,
                        conversation_title=conversation.title,
                        request_id=getattr(request.state, "request_id", None),
                    )
        return None
    finally:
        plan.message = response_message
        plan.requested_tool = requested_tool
        plan.tool_arguments = tool_arguments
        plan.selected_patient_id = selected_patient_id


async def _attach_confirmation(
    state: dict[str, Any],
    *,
    db: AsyncSession,
    payload: ChatRequest,
    session_id: str,
    current_user: User,
) -> None:
    """Load the persisted pending write and rebuild its tool-call message."""
    assert payload.confirmation is not None
    # Tool, arguments, and call id come only from the persisted record.
    record = await confirmation_store.load_active(
        db,
        payload.confirmation.token,
        session_id=session_id,
        user_id=current_user.id,
    )
    if record is None:
        raise AppError("AGENT_CONFIRMATION_INVALID")
    pending_action = {
        "tool_name": record.tool_name,
        "arguments": dict(record.arguments),
        "tool_call_id": record.tool_call_id,
    }
    state["pending_action"] = pending_action
    state["pending_tool_calls"] = [dict(pending_action)]
    state["confirmation_status"] = "pending"
    # Rebuild the assistant tool-call message from the persisted record.
    # The tool result appended after execution must have a matching
    # preceding tool_call for OpenAI-compatible chat APIs.
    state["messages"].append(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                # Persisted arguments may contain the server-resolved
                # appointment id; never replay it to the model.
                safe_tool_call_for_history(
                    record.tool_name,
                    dict(record.arguments),
                    record.tool_call_id,
                )
            ],
        }
    )


@router.post(
    "/chat",
    response_model=ChatResponse,
    dependencies=[Depends(chat_rate_limit)],
)
async def agent_chat(
    payload: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    llm: ToolCallingChatModel = Depends(get_chat_llm),
):
    """Run one assistant turn for the authenticated user.

    History: the server-side conversation is the source of truth. Client
    ``history`` only seeds a brand-new conversation; once turns exist in the
    database the client-supplied list is ignored.
    """
    if payload.confirmation is not None and payload.session_id is None:
        # Never silently start a fresh session for an approval: that would
        # hide the fact that the original pending action cannot be recovered.
        raise AppError("AGENT_CONFIRMATION_INVALID")

    owned_patients = await _owned_patient_dicts(db, current_user)
    if current_user.role == "patient" and not owned_patients:
        # Registration is a hard gate: no conversation or model call can start
        # before the account has at least one patient record.
        raise AppError("PATIENT_ACCOUNT_NOT_LINKED")

    session_id = payload.session_id or uuid4().hex
    conversation = await chat_history.get_or_create_conversation(
        db, user_id=current_user.id, session_id=session_id
    )

    owned_patient_ids = {
        int(patient["id"])
        for patient in owned_patients
        if isinstance(patient.get("id"), int)
    }
    selected_patient_id = conversation.selected_patient_id
    if selected_patient_id not in owned_patient_ids:
        selected_patient_id = None
    if selected_patient_id is None and len(owned_patient_ids) == 1:
        selected_patient_id = next(iter(owned_patient_ids))
        conversation.selected_patient_id = selected_patient_id
        await db.commit()

    # --- Server-owned history for the model context -----------------------
    persisted = await chat_history.list_messages(
        db,
        conversation_id=conversation.id,
        limit=chat_history.MAX_CONTEXT_TURNS,
    )
    history = (
        chat_history.context_from_messages(persisted)
        if persisted
        else [
            {"role": item.role, "content": item.content}
            for item in payload.history
        ]
    )

    active_kind: str | None = conversation.options_kind
    active_payload: dict[str, Any] | None = conversation.options_payload
    active_count = len(
        list_option_items(active_kind, active_payload) or []
    )

    plan = _TurnPlan(
        message=payload.message, selected_patient_id=selected_patient_id
    )
    early_response = await _resolve_numeric_option(
        plan,
        db=db,
        request=request,
        payload=payload,
        conversation=conversation,
        session_id=session_id,
        owned_patients=owned_patients,
        owned_patient_ids=owned_patient_ids,
        active_kind=active_kind,
        active_payload=active_payload,
        active_count=active_count,
    )
    if early_response is not None:
        return early_response
    response_message = plan.message
    requested_tool = plan.requested_tool
    tool_arguments = plan.tool_arguments
    selected_patient_id = plan.selected_patient_id

    context: dict = {
        "db": db,
        "llm": llm,
        "session_id": session_id,
        "actor": current_user,
        "selected_patient_id": selected_patient_id,
    }
    if payload.confirmation is not None:
        context["confirmation"] = payload.confirmation.model_dump()

    state = create_initial_state(
        messages=[
            *history,
            {"role": "user", "content": response_message},
        ],
        requested_tool=requested_tool,
        tool_arguments=tool_arguments,
    )

    if payload.confirmation is not None:
        await _attach_confirmation(
            state,
            db=db,
            payload=payload,
            session_id=session_id,
            current_user=current_user,
        )

    try:
        result = await agent_graph.ainvoke(
            state,
            context=context,
            config={"recursion_limit": AGENT_RECURSION_LIMIT},
        )
    except GraphRecursionError:
        # The decision node has its own step cap. This is a second line of
        # defence so a graph-loop failure becomes a safe Persian reply instead
        # of an HTTP 500. No pending write is executed or confirmed.
        logger.warning("Agent graph recursion limit reached")
        reply = _recursion_fallback_reply()
        await chat_history.append_turn(
            db,
            conversation=conversation,
            user_text=payload.message,
            assistant_text=reply,
            assistant_available=True,
        )
        return ChatResponse(
            reply=reply,
            confirmation_required=False,
            suggested_appointments=[],
            slots=[],
            session_id=session_id,
            conversation_title=conversation.title,
            request_id=getattr(request.state, "request_id", None),
        )

    reply = result.get("final_response") or ""
    forced_options: tuple[str, dict[str, Any]] | None = None
    if (
        _tool_error_code(result) == "PATIENT_SELECTION_REQUIRED"
        and len(owned_patients) > 1
    ):
        forced_options = build_patient_options(owned_patients)
        if forced_options is not None:
            # The same selection is required for booking and for listing an
            # account's appointments, so keep the wording action-neutral.
            reply = "این درخواست برای کدام بیمار از پرونده‌های حساب شما انجام شود؟"

    conversation = await chat_history.reload_conversation(db, conversation)
    if conversation is not None:
        await chat_history.append_turn(
            db,
            conversation=conversation,
            user_text=payload.message,
            assistant_text=reply,
            assistant_available=bool(reply),
        )

    if forced_options is not None:
        kind, option_payload = forced_options
    else:
        requested_times: set[str] = set()
        for entry in history:
            if entry.get("role") == "user":
                requested_times |= explicit_clock_times(
                    str(entry.get("content") or "")
                )
        requested_times |= explicit_clock_times(payload.message)
        kind, option_payload = _turn_active_options(
            result, requested_times=requested_times
        )
        if kind == "appointment" and isinstance(option_payload, dict):
            await _fill_appointment_option_names(db, option_payload)
    if conversation is not None:
        await chat_history.save_active_options(
            db, conversation=conversation, kind=kind, payload=option_payload
        )

    suggested = _suggested_appointments(result)
    return ChatResponse(
        reply=reply,
        confirmation_required=bool(result.get("confirmation_required")),
        confirmation_prompt=result.get("confirmation_prompt"),
        confirmation_token=result.get("confirmation_token"),
        suggested_appointments=suggested,
        slots=suggested,
        options=_options_response(kind, option_payload),
        form_required=_form_required(result, current_user),
        session_id=session_id,
        # reload_conversation() may return None after a double database
        # failure; the computed reply must still reach the client (an
        # executed write's confirmation cannot be re-issued), so degrade
        # the title instead of failing the whole response with a 500.
        conversation_title=conversation.title if conversation is not None else None,
        request_id=getattr(request.state, "request_id", None),
    )


@router.get(
    "/conversations",
    response_model=list[ChatConversation],
)
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the authenticated user's own agent conversations."""
    rows = await chat_history.list_conversations(db, user_id=current_user.id)
    return [
        ChatConversation(
            session_id=row.session_id,
            title=row.title,
            created_at=row.created_at,
            updated_at=row.updated_at,
            message_count=int(count or 0),
        )
        for row, count in rows
    ]


@router.post(
    "/conversations",
    response_model=ChatConversation,
    status_code=201,
)
async def create_conversation(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start a new empty conversation owned by the authenticated user."""
    conversation = await chat_history.create_conversation(
        db, user_id=current_user.id
    )
    return ChatConversation(
        session_id=conversation.session_id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=0,
    )


@router.get(
    "/conversations/{session_id}",
    response_model=ChatConversationDetail,
)
async def get_conversation(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch one owned conversation with its user/assistant turns.

    A session id owned by another user is just 404 in this namespace: no
    details about foreign conversations are ever returned.
    """
    conversation = await chat_history.get_conversation(
        db, user_id=current_user.id, session_id=session_id
    )
    messages = await chat_history.list_messages(
        db, conversation_id=conversation.id, limit=100
    )
    return ChatConversationDetail(
        session_id=conversation.session_id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=len(messages),
        messages=[
            ChatMessageOut(
                role=message.role,  # type: ignore[arg-type]
                content=message.content,
                created_at=message.created_at,
            )
            for message in messages
            if message.role in ("user", "assistant")
        ],
    )


@router.delete("/conversations/{session_id}")
async def delete_conversation(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete one owned conversation and its history; foreign ids are 404."""
    await chat_history.delete_conversation(
        db, user_id=current_user.id, session_id=session_id
    )
    return {
        "message": "گفتگو و تاریخچه آن حذف شد.",
        "session_id": session_id,
    }
