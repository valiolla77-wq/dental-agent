"""LangGraph orchestration for chat decisions and allowlisted tools."""

import json
import logging
from datetime import datetime
from typing import Any, TypedDict
from uuid import uuid4

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from pydantic import ValidationError
from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.confirmations import ConfirmationDecision, confirmation_store
from app.agent.llm import ToolCallingChatModel, create_chat_model
from app.agent.prompts import build_system_prompt
from app.agent.registry import (
    PATIENT_BOUND_FIELDS,
    TOOL_REGISTRY,
    ToolDefinition,
    get_llm_tool_schemas,
)
from app.agent.state import AgentState, ConversationMessage, PendingAction, PendingToolCall
from app.agent_tools.schemas import AgentToolError
from app.auth.permissions import actor_role, authorize_tool_call, linked_patient_id
from app.errors import ERROR_CATALOG, AppError
from app.models.appointment import Appointment
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.user import User
from app.services.appointment_service import validate_appointment_slot
from app.utils.date_utils import gregorian_to_jalali


logger = logging.getLogger("dental_agent.agent")

# Each model/tool round costs about two graph supersteps. This explicit cap is
# enforced in the decision node (and a slightly larger LangGraph recursion
# limit is a second line of defence) so a looping model cannot run unbounded.
MAX_AGENT_STEPS = 12
AGENT_RECURSION_LIMIT = MAX_AGENT_STEPS * 2 + 8


class AgentContext(TypedDict, total=False):
    """Trusted per-invoke inputs from the host: dependencies, session identity,
    the authenticated actor, and the confirmation decision. Nothing here
    round-trips through AgentState."""

    db: AsyncSession
    llm: ToolCallingChatModel
    session_id: str | None
    actor: User | None
    confirmation: ConfirmationDecision
    # Test/host injection only. The HTTP router never accepts this from a
    # client; production leaves it unset so the service uses the real clock.
    now: datetime | None


def _append_message(
    state: AgentState,
    role: str,
    content: Any,
    **metadata: Any,
) -> list[ConversationMessage]:
    message: ConversationMessage = {"role": role, "content": content, **metadata}  # type: ignore[typeddict-item]
    return [*state.get("messages", []), message]


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        )
    return str(content) if content is not None else ""


def _messages_for_model(
    state: AgentState, *, patient_bound: bool = False
) -> list[BaseMessage]:
    messages: list[BaseMessage] = [
        SystemMessage(
            content=build_system_prompt(patient_bound=patient_bound)
        )
    ]
    for item in state.get("messages", []):
        role = item["role"]
        content = item.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "system":
            messages.append(SystemMessage(content=content))
        elif role == "assistant":
            tool_calls = item.get("tool_calls", [])
            messages.append(
                AIMessage(content=content, tool_calls=tool_calls)
                if tool_calls
                else AIMessage(content=content)
            )
        elif role == "tool":
            messages.append(
                ToolMessage(
                    content=content,
                    tool_call_id=item["tool_call_id"],
                    name=item.get("name"),
                )
            )
    return messages


def _safe_tool_call_for_history(
    name: str,
    arguments: dict[str, Any],
    call_id: str,
) -> dict[str, Any]:
    # Sensitive booking fields are needed by the Tool but not by later LLM turns.
    safe_arguments = {
        key: value
        for key, value in arguments.items()
        if key not in {"national_id", "full_name", "phone", "reason"}
    }
    return {"name": name, "args": safe_arguments, "id": call_id, "type": "tool_call"}


async def _stable_actor(runtime: Runtime[AgentContext]) -> User | None:
    """Return the trusted actor, refreshing it only when the ORM expired it.

    A failed write rolls the session back, which expires every loaded ORM
    instance. Reading ``actor.id``/``actor.role`` afterwards could trigger a
    lazy load outside the async/greenlet context (``MissingGreenlet``). Test
    doubles that are transient/detached keep their in-memory attributes.
    """
    actor = runtime.context.get("actor")
    db = runtime.context.get("db")
    if actor is None or db is None:
        return None
    try:
        state = sa_inspect(actor)
        if state.persistent and state.expired:
            await db.refresh(actor)
    except Exception:
        logger.warning("Agent actor could not be refreshed; failing closed")
        return None
    return actor


def _is_patient_actor(actor: User | None) -> bool:
    return actor is not None and actor_role(actor) == "patient"


async def _prepare_patient_call(
    runtime: Runtime[AgentContext],
    call: dict[str, Any],
    actor: User | None,
) -> tuple[dict[str, Any], AgentToolError | None]:
    """Force the authenticated patient's own id into patient-bound tools.

    The model may omit identity or try to supply somebody else's id/national
    id. For patient-role actors every identity argument is removed and replaced
    with the linked patient record. Staff callers are unaffected. The
    authorization choke point still re-checks ownership before execution.
    """
    if not _is_patient_actor(actor):
        return call, None

    name = call.get("tool_name")
    hidden = PATIENT_BOUND_FIELDS.get(name or "")
    if not hidden:
        return call, None

    linked = await linked_patient_id(runtime.context["db"], actor)
    if linked is None:
        return call, _catalog_error("PATIENT_ACCOUNT_NOT_LINKED")

    arguments = dict(call.get("arguments") or {})
    bound = {
        key: value for key, value in arguments.items() if key not in hidden
    }
    bound["patient_id"] = linked
    return {**call, "arguments": bound}, None


def _confirmation_prompt(action: PendingAction) -> str:
    """Safe id-based fallback used only when no richer description is possible."""
    name = action.get("tool_name")
    args = action.get("arguments") or {}
    labels = {
        "book_appointment": "ثبت نوبت",
        "cancel_appointment": "لغو نوبت",
        "reschedule_appointment": "جابه‌جایی نوبت",
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
            f" نوبت {args.get('appointment_id', 'نامشخص')} به تاریخ "
            f"{args.get('appointment_date', 'نامشخص')} ساعت "
            f"{args.get('appointment_time', 'نامشخص')}"
        )
    elif name == "cancel_appointment":
        summary += f" شماره {args.get('appointment_id', 'نامشخص')}"
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
        appointment_date, appointment_time = gregorian_to_jalali(slot)

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
        current_date, current_time = gregorian_to_jalali(
            appointment.appointment_time
        )
        doctor = await db.get(Doctor, appointment.doctor_id)
        service = await db.get(DentalService, appointment.service_id)
        doctor_name = doctor.full_name if doctor is not None else "پزشک ثبت‌شده"
        service_name = service.name if service is not None else "خدمت ثبت‌شده"

        if name == "cancel_appointment":
            return (
                f"لغو نوبت شماره {appointment.id} برای «{service_name}» با "
                f"{doctor_name} در تاریخ {current_date} ساعت {current_time} "
                "را تأیید می‌کنید؟"
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
        target_date, target_time = gregorian_to_jalali(target)
        return (
            f"جابه‌جایی نوبت شماره {appointment.id} برای «{service_name}» با "
            f"{doctor_name} از تاریخ {current_date} ساعت {current_time} "
            f"به تاریخ {target_date} ساعت {target_time} را تأیید می‌کنید؟"
        )

    return _confirmation_prompt(action)


def _catalog_error(code: str) -> AgentToolError:
    definition = ERROR_CATALOG[code]
    return AgentToolError(code=definition.code, message=definition.message, details={})


def _successful_write_fallback(state: AgentState) -> str | None:
    """Describe a committed write when only the final LLM phrasing failed.

    The fallback is derived exclusively from the successful tool result. It
    never runs the tool again and returns None for failed or non-write tools,
    so an error cannot be reported as a success.
    """
    name = state.get("last_tool_name")
    result = state.get("last_tool_result")
    if name not in {
        "book_appointment",
        "cancel_appointment",
        "reschedule_appointment",
    }:
        return None
    if not isinstance(result, dict) or not result.get("ok"):
        return None
    data = result.get("data")
    if not isinstance(data, dict):
        return None

    appointment_id = data.get("appointment_id")
    if name == "book_appointment":
        if appointment_id is None:
            return "نوبت با موفقیت ثبت شد."
        appointment_time = data.get("appointment_time")
        if appointment_time:
            return f"نوبت {appointment_id} برای {appointment_time} ثبت شد."
        return f"نوبت {appointment_id} با موفقیت ثبت شد."

    if name == "cancel_appointment":
        if appointment_id is None:
            return "نوبت با موفقیت لغو شد."
        return f"نوبت {appointment_id} لغو شد."

    appointment_time = data.get("appointment_time")
    if appointment_id is None:
        return "نوبت با موفقیت جابه‌جا شد."
    if appointment_time:
        return f"نوبت {appointment_id} به {appointment_time} منتقل شد."
    return f"نوبت {appointment_id} با موفقیت جابه‌جا شد."


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
        "route": "finish",
        "final_response": response,
        "messages": _append_message(state, "assistant", response),
        "step_count": steps,
    }


async def _agent_decision_impl(
    state: AgentState,
    runtime: Runtime[AgentContext],
) -> dict[str, Any]:
    actor = await _stable_actor(runtime)
    pending_action = state.get("pending_action")

    if pending_action is not None:
        if not isinstance(pending_action, dict):
            return _finish_rejected_confirmation(state)
        # Untrusted state claims (e.g. confirmation_status="approved") never
        # authorize execution. Approval must arrive via the host-owned
        # AgentContext and match the server-side record issued for this exact
        # session, tool, and displayed arguments; records are single-use.
        decision = runtime.context.get("confirmation")
        session_id = runtime.context.get("session_id")
        user_id = actor.id if actor is not None else None
        legacy_rejected = state.get("confirmation_status", "not_required") == "rejected"
        context_rejected = (
            isinstance(decision, dict) and decision.get("decision") == "rejected"
        )

        if legacy_rejected or context_rejected:
            token = state.get("confirmation_token")
            if isinstance(decision, dict) and decision.get("token"):
                token = decision.get("token")
            await confirmation_store.consume(
                runtime.context["db"],
                token,
                session_id=session_id,
                user_id=user_id,
                decision="rejected",
            )
            return _finish_rejected_confirmation(state)

        if not (isinstance(decision, dict) and decision.get("decision") == "approved"):
            return {
                "confirmation_required": True,
                "confirmation_status": "pending",
                "route": "confirmation",
            }

        record = await confirmation_store.consume(
            runtime.context["db"],
            decision.get("token"),
            session_id=session_id,
            user_id=user_id,
            decision="approved",
        )
        if (
            record is None
            or record.tool_name != pending_action.get("tool_name")
            or record.arguments != pending_action.get("arguments")
            or record.tool_call_id != pending_action.get("tool_call_id")
        ):
            # Unknown or consumed token, another session, or the pending action
            # no longer matches what was displayed for confirmation.
            return _finish_rejected_confirmation(state)

        pending_calls = list(state.get("pending_tool_calls", []))
        if pending_calls:
            pending_calls.pop(0)
        return {
            "pending_tool_calls": pending_calls,
            "pending_action": None,
            "confirmation_token": None,
            "selected_tool": record.tool_name,
            "selected_tool_arguments": dict(record.arguments),
            "selected_tool_call_id": record.tool_call_id,
            "confirmation_required": True,
            "route": "execute_tool",
            "final_response": None,
        }

    # Compatibility/testing input: a host may supply a preselected allowlisted
    # tool while no model decision node is configured.
    if state.get("requested_tool"):
        call_id = f"host-{uuid4()}"
        name = state["requested_tool"]
        arguments = state.get("tool_arguments", {})
        pending_calls = list(state.get("pending_tool_calls", []))
        pending_calls.append(
            {"tool_name": name, "arguments": arguments, "tool_call_id": call_id}
        )
        safe_call = _safe_tool_call_for_history(name, arguments, call_id)
        history = _append_message(
            state,
            "assistant",
            "",
            tool_calls=[safe_call],
        )
        return {
            "requested_tool": None,
            "tool_arguments": {},
            "messages": history,
            "pending_tool_calls": pending_calls,
            "route": "continue",
        }

    pending_calls = list(state.get("pending_tool_calls", []))
    if pending_calls:
        call = pending_calls[0]
        definition = TOOL_REGISTRY.get(call["tool_name"])
        if definition is None:
            pending_calls.pop(0)
            error = _catalog_error("COMMON_VALIDATION_ERROR")
            result = {"ok": False, "data": None, "error": error.model_dump(mode="json")}
            messages = _append_message(
                state,
                "tool",
                json.dumps(result, ensure_ascii=False),
                tool_call_id=call["tool_call_id"],
                name=call["tool_name"],
            )
            return {
                "pending_tool_calls": pending_calls,
                "last_tool_result": result,
                "last_tool_error": error,
                "messages": messages,
                "route": "continue",
            }

        # Force the authenticated patient's identity before validation. This
        # is the security boundary; hiding schema fields is only UX.
        call, binding_error = await _prepare_patient_call(runtime, call, actor)
        if binding_error is not None:
            pending_calls.pop(0)
            result = {
                "ok": False,
                "data": None,
                "error": binding_error.model_dump(mode="json"),
            }
            messages = _append_message(
                state,
                "tool",
                json.dumps(result, ensure_ascii=False),
                tool_call_id=call["tool_call_id"],
                name=call["tool_name"],
            )
            return {
                "pending_tool_calls": pending_calls,
                "last_tool_result": result,
                "last_tool_error": binding_error,
                "messages": messages,
                "route": "continue",
            }

        try:
            validated_arguments = definition.input_schema.model_validate(
                call["arguments"]
            )
        except ValidationError:
            pending_calls.pop(0)
            error = _catalog_error("COMMON_VALIDATION_ERROR")
            result = {"ok": False, "data": None, "error": error.model_dump(mode="json")}
            messages = _append_message(
                state,
                "tool",
                json.dumps(result, ensure_ascii=False),
                tool_call_id=call["tool_call_id"],
                name=call["tool_name"],
            )
            return {
                "pending_tool_calls": pending_calls,
                "last_tool_result": result,
                "last_tool_error": error,
                "messages": messages,
                "route": "continue",
            }
        call = {
            **call,
            "arguments": validated_arguments.model_dump(),
        }
        pending_calls[0] = call
        if definition.operation == "write":
            action: PendingAction = {
                "tool_name": call["tool_name"],
                "arguments": call["arguments"],
                "tool_call_id": call["tool_call_id"],
            }
            return {
                "pending_action": action,
                "confirmation_required": True,
                "confirmation_status": "pending",
                "route": "confirmation",
            }
        pending_calls.pop(0)
        return {
            "pending_tool_calls": pending_calls,
            "selected_tool": call["tool_name"],
            "selected_tool_arguments": call["arguments"],
            "selected_tool_call_id": call["tool_call_id"],
            "confirmation_required": False,
            "confirmation_status": "not_required",
            "route": "execute_tool",
        }

    model = runtime.context.get("llm") or create_chat_model()
    patient_bound = _is_patient_actor(actor)
    try:
        response = await model.bind_tools(
            get_llm_tool_schemas(patient_bound=patient_bound)
        ).ainvoke(_messages_for_model(state, patient_bound=patient_bound))
    except Exception as exc:
        logger.error(
            "Agent LLM request failed (%s); exception details omitted",
            type(exc).__name__,
        )
        fallback = _successful_write_fallback(state)
        if fallback is not None:
            return {
                "last_tool_result": state.get("last_tool_result"),
                "last_tool_error": state.get("last_tool_error"),
                "final_response": fallback,
                "route": "finish",
                "messages": _append_message(state, "assistant", fallback),
            }
        error = _catalog_error("INTERNAL_ERROR")
        result = {"ok": False, "data": None, "error": error.model_dump(mode="json")}
        final_response = error.message
        return {
            "last_tool_result": result,
            "last_tool_error": error,
            "final_response": final_response,
            "route": "finish",
            "messages": _append_message(state, "assistant", final_response),
        }

    calls: list[PendingToolCall] = []
    history_calls: list[dict[str, Any]] = []
    for call in getattr(response, "tool_calls", []) or []:
        name = call.get("name")
        arguments = call.get("args")
        call_id = call.get("id") or str(uuid4())
        if not isinstance(name, str) or not isinstance(arguments, dict):
            continue
        calls.append(
            {"tool_name": name, "arguments": arguments, "tool_call_id": call_id}
        )
        history_calls.append(_safe_tool_call_for_history(name, arguments, call_id))

    if calls:
        return {
            "messages": _append_message(
                state,
                "assistant",
                getattr(response, "content", ""),
                tool_calls=history_calls,
            ),
            "pending_tool_calls": calls,
            "requested_tool": None,
            "confirmation_required": False,
            "confirmation_status": "not_required",
            "final_response": None,
            "route": "continue",
        }

    final_response = _message_content_to_text(getattr(response, "content", ""))
    if not final_response:
        final_response = "متوجه درخواست نشدم؛ لطفاً آن را واضح‌تر بیان کنید."
    return {
        "messages": _append_message(state, "assistant", final_response),
        "final_response": final_response,
        "confirmation_required": False,
        "confirmation_status": "not_required",
        "route": "finish",
    }


async def _agent_decision_node(
    state: AgentState,
    runtime: Runtime[AgentContext],
) -> dict[str, Any]:
    """Step-capped wrapper around the decision node."""
    try:
        steps = int(state.get("step_count", 0) or 0) + 1
    except (TypeError, ValueError):
        steps = MAX_AGENT_STEPS + 1
    if steps > MAX_AGENT_STEPS:
        logger.warning("Agent step limit reached; ending without a write")
        return _finish_step_limit(state, steps)

    try:
        updates = await _agent_decision_impl(state, runtime)
    except AppError as exc:
        updates = _finish_error(state, exc.code)
    except Exception as exc:  # noqa: BLE001 - never expose internals
        logger.error(
            "Agent decision failed (%s); exception details omitted",
            type(exc).__name__,
        )
        updates = _finish_error(state, "INTERNAL_ERROR")
    updates["step_count"] = steps
    return updates


async def _confirmation_node(
    state: AgentState,
    runtime: Runtime[AgentContext],
) -> dict[str, Any]:
    action = state.get("pending_action")
    if not isinstance(action, dict):
        return _finish_error(state, "COMMON_VALIDATION_ERROR")

    name = action.get("tool_name") or ""
    definition = TOOL_REGISTRY.get(name)
    if definition is None or definition.operation != "write":
        return _finish_error(state, "COMMON_VALIDATION_ERROR")

    actor = await _stable_actor(runtime)
    db = runtime.context["db"]
    try:
        # Authorize before showing any database-derived appointment details.
        # A patient must not learn anything about somebody else's appointment.
        await authorize_tool_call(
            db,
            actor,
            name,
            action.get("arguments") or {},
        )
        prompt = await _describe_action(
            db,
            action,
            actor,
            now=runtime.context.get("now"),
        )
    except AppError as exc:
        return _finish_error(state, exc.code)
    except Exception as exc:  # noqa: BLE001 - never expose internals
        logger.error(
            "Agent confirmation description failed (%s); details omitted",
            type(exc).__name__,
        )
        return _finish_error(state, "INTERNAL_ERROR")

    user_id = actor.id if actor is not None else None
    try:
        record = await confirmation_store.issue(
            db,
            session_id=runtime.context.get("session_id"),
            user_id=user_id,
            tool_name=name,
            arguments=action.get("arguments") or {},
            tool_call_id=action.get("tool_call_id") or str(uuid4()),
        )
    except AppError as exc:
        return _finish_error(state, exc.code)
    except Exception as exc:  # noqa: BLE001 - never expose internals
        logger.error(
            "Agent confirmation issue failed (%s); details omitted",
            type(exc).__name__,
        )
        return _finish_error(state, "INTERNAL_ERROR")

    return {
        "confirmation_required": True,
        "confirmation_status": "pending",
        "confirmation_token": record.token,
        "confirmation_prompt": prompt,
        "final_response": prompt,
        "messages": _append_message(state, "assistant", prompt),
    }


async def _tool_execution_node(
    state: AgentState,
    runtime: Runtime[AgentContext],
) -> dict[str, Any]:
    name = state.get("selected_tool")
    definition: ToolDefinition | None = TOOL_REGISTRY.get(name or "")
    call_id = state.get("selected_tool_call_id") or str(uuid4())
    arguments = state.get("selected_tool_arguments", {})
    actor = await _stable_actor(runtime)
    if definition is None:
        error = _catalog_error("COMMON_VALIDATION_ERROR")
        result = {"ok": False, "data": None, "error": error.model_dump(mode="json")}
    else:
        try:
            # Authorization choke point: identity comes only from the trusted
            # host context. No handler runs without a permitted actor.
            await authorize_tool_call(
                runtime.context["db"],
                actor,
                name or "",
                arguments if isinstance(arguments, dict) else {},
            )
            validated = definition.input_schema.model_validate(arguments)
            result_object = await definition.handler(
                runtime.context["db"],
                **validated.model_dump(),
            )
            result = result_object.model_dump(mode="json")
            error = result_object.error
        except AppError as exc:
            error = _catalog_error(exc.code)
            result = {"ok": False, "data": None, "error": error.model_dump(mode="json")}
        except ValidationError:
            error = _catalog_error("COMMON_VALIDATION_ERROR")
            result = {"ok": False, "data": None, "error": error.model_dump(mode="json")}
        except Exception as exc:
            logger.error(
                "Agent tool dispatch failed (%s); exception details omitted",
                type(exc).__name__,
            )
            error = _catalog_error("INTERNAL_ERROR")
            result = {"ok": False, "data": None, "error": error.model_dump(mode="json")}

    messages = _append_message(
        state,
        "tool",
        json.dumps(result, ensure_ascii=False),
        tool_call_id=call_id,
        name=name or "unknown",
    )
    return {
        "messages": messages,
        "last_tool_result": result,
        "last_tool_error": error,
        "last_tool_name": name or "unknown",
        "selected_tool": None,
        "selected_tool_arguments": {},
        "selected_tool_call_id": None,
        "confirmation_required": False,
        "confirmation_status": "not_required",
    }


def _route_from_decision(state: AgentState) -> str:
    return state.get("route", "finish")


def create_agent_graph():
    """Build the provider-neutral graph; a host may inject a fake chat model."""
    builder = StateGraph(AgentState, context_schema=AgentContext)
    builder.add_node("agent_decision", _agent_decision_node)
    builder.add_node("confirmation_gate", _confirmation_node)
    builder.add_node("tool_execution", _tool_execution_node)
    builder.add_edge(START, "agent_decision")
    builder.add_conditional_edges(
        "agent_decision",
        _route_from_decision,
        {
            "continue": "agent_decision",
            "execute_tool": "tool_execution",
            "confirmation": "confirmation_gate",
            "finish": END,
        },
    )
    builder.add_edge("confirmation_gate", END)
    builder.add_edge("tool_execution", "agent_decision")
    return builder.compile()


agent_graph = create_agent_graph()
