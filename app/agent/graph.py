"""LangGraph orchestration for chat decisions and allowlisted tools."""

import json
import logging
from typing import Any
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from pydantic import ValidationError

from app.agent.appointment_selection import (
    PAST_DESTINATION_MESSAGE,
    PAST_TARGET_MESSAGE,
    booking_criteria_mismatch,
    normalize_text,
    parse_reschedule_destination,
    resolve_appointment_target,
)
from app.agent.confirmation_text import (
    _describe_action,
    _destination_text,
    _target_selection_text,
)
from app.agent.confirmations import confirmation_store
from app.agent.context import AGENT_RECURSION_LIMIT, MAX_AGENT_STEPS, AgentContext
from app.agent.llm import create_chat_model
from app.agent.messages import (
    _all_user_texts,
    _append_message,
    _latest_assistant_text,
    _latest_user_text,
    _message_content_to_text,
    _messages_for_model,
    safe_tool_call_for_history,
)
from app.agent.nudges import (
    _CANCEL_RESCHEDULE_MARKERS,
    _turn_had_tool_error,
    _turn_tool_names,
    degenerate_list_clarification,
    empty_retry_clarification,
    stall_directive,
)
from app.agent.outcomes import (
    _catalog_error,
    _finish_clarification,
    _finish_error,
    _finish_rejected_confirmation,
    _finish_step_limit,
    _provider_failure_code,
    _sanitize_write_final_response,
    _successful_write_fallback,
)
from app.agent.patient_binding import _is_patient_actor, _prepare_patient_call, _stable_actor
from app.agent.registry import (
    TOOL_REGISTRY,
    ToolDefinition,
    get_llm_tool_schemas,
)
from app.agent.state import AgentState, PendingAction, PendingToolCall
from app.agent_tools.schemas import AgentToolError
from app.auth.permissions import (
    actor_role,
    authorize_tool_call,
    linked_patient_ids,
)
from app.errors import AppError
from app.models.user import User
from app.services.audit_service import record_audit
from app.services.appointment_service import clinic_now, validate_appointment_slot

logger = logging.getLogger("dental_agent.agent")


def _tool_denied_label(actor: User | None) -> str | None:
    """Stable, non-sensitive label of the denied caller for the audit row."""
    if actor is None:
        return None
    return f"{actor.role}:{actor.phone}"

# Public surface, re-exported for the HTTP router and tests. Everything else
# lives in the sibling modules (context, messages, patient_binding,
# confirmation_text, outcomes) and is internal.
__all__ = [
    "AGENT_RECURSION_LIMIT",
    "MAX_AGENT_STEPS",
    "AgentContext",
    "agent_graph",
    "create_agent_graph",
    "safe_tool_call_for_history",
]


async def _authorize_tool_call_audited(
    runtime: Runtime[AgentContext],
    actor: User | None,
    tool_name: str,
    arguments: object,
) -> None:
    """Authorize a tool call and audit role denials of staff-facing tools.

    The denial itself still fails closed; the audit row is best-effort and
    never turns a rejection into a success.
    """
    db = runtime.context["db"]
    try:
        await authorize_tool_call(db, actor, tool_name, arguments)
    except AppError as exc:
        if exc.code == "COMMON_FORBIDDEN":
            try:
                await record_audit(
                    db,
                    actor=actor,
                    action="agent.tool.denied",
                    target_label=_tool_denied_label(actor),
                    detail={"tool": tool_name},
                )
            except Exception:  # noqa: BLE001 - audit must not break the turn
                logger.warning(
                    "Could not record agent tool denial for %s",
                    tool_name,
                )
        raise


def _tool_error_update(
    state: AgentState,
    pending_calls: list[PendingToolCall],
    call: PendingToolCall,
    error: AgentToolError,
) -> dict[str, Any]:
    """Drop a failed call from the queue and report it to the model as a tool result."""
    pending_calls.pop(0)
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


async def _resolve_pending_action(
    state: AgentState,
    runtime: Runtime[AgentContext],
    actor: User | None,
) -> dict[str, Any]:
    """Phase 1: settle a write that is waiting for the user's confirmation."""
    pending_action = state.get("pending_action")
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


def _queue_host_requested_tool(state: AgentState) -> dict[str, Any]:
    """Phase 2: queue a preselected allowlisted tool supplied by the host.

    Compatibility/testing input, and the path the router uses for a
    deterministic booking after an option number was resolved server-side.
    """
    call_id = f"host-{uuid4()}"
    name = state["requested_tool"]
    arguments = state.get("tool_arguments", {})
    pending_calls = list(state.get("pending_tool_calls", []))
    pending_calls.append(
        {"tool_name": name, "arguments": arguments, "tool_call_id": call_id}
    )
    safe_call = safe_tool_call_for_history(name, arguments, call_id)
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


async def _process_pending_call(
    state: AgentState,
    runtime: Runtime[AgentContext],
    actor: User | None,
) -> dict[str, Any]:
    """Phase 3: validate the next queued call; reads run, writes need a confirmation."""
    pending_calls = list(state.get("pending_tool_calls", []))
    call = pending_calls[0]
    definition = TOOL_REGISTRY.get(call["tool_name"])
    if definition is None:
        return _tool_error_update(
            state, pending_calls, call, _catalog_error("COMMON_VALIDATION_ERROR")
        )

    # Force the authenticated patient's identity before validation. This is the
    # security boundary; hiding schema fields is only UX.
    call, binding_error = await _prepare_patient_call(runtime, call, actor)
    if binding_error is not None:
        return _tool_error_update(state, pending_calls, call, binding_error)

    try:
        validated_arguments = definition.input_schema.model_validate(call["arguments"])
    except ValidationError:
        return _tool_error_update(
            state, pending_calls, call, _catalog_error("COMMON_VALIDATION_ERROR")
        )
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


async def _model_failure_update(
    exc: Exception,
    state: AgentState,
    runtime: Runtime[AgentContext],
) -> dict[str, Any]:
    """Turn an LLM request failure into a safe reply, or a retryable 503."""
    logger.error(
        "Agent LLM request failed (%s); exception details omitted",
        type(exc).__name__,
    )
    fallback = await _successful_write_fallback(
        runtime.context["db"], state
    )
    if fallback is not None:
        return {
            "last_tool_result": state.get("last_tool_result"),
            "last_tool_error": state.get("last_tool_error"),
            "final_response": fallback,
            "route": "finish",
            "messages": _append_message(state, "assistant", fallback),
        }
    provider_code = _provider_failure_code(exc)
    if provider_code is not None:
        # Surface this as a retryable HTTP 503 instead of persisting a
        # generic "internal error" turn. The client can retry the same
        # message without duplicating a server-side chat turn.
        raise AppError(provider_code) from exc
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


async def _interpret_model_response(
    response: Any,
    state: AgentState,
    runtime: Runtime[AgentContext],
) -> tuple[dict[str, Any], bool]:
    """Phase 4b: queue the model's tool calls, or finish with its text reply.

    Also returns whether the finish was *empty*: no usable tool call and
    no text, the shape that lands on the «متوجه درخواست نشدم» fallback.
    Calls the provider could not parse (``invalid_tool_calls`` — through
    the OpenAI-compatible proxy, argument JSON sometimes arrives as a
    string) and calls failing the shape filter are logged with their
    name and reason before being dropped; in the eval they vanished
    silently and the turn looked like a deliberate blank reply.
    """
    calls: list[PendingToolCall] = []
    history_calls: list[dict[str, Any]] = []
    for call in getattr(response, "tool_calls", []) or []:
        name = call.get("name")
        arguments = call.get("args")
        call_id = call.get("id") or str(uuid4())
        if not isinstance(name, str) or not isinstance(arguments, dict):
            logger.warning(
                "Dropping unusable model tool call (name type %s, "
                "args type %s); call content omitted",
                type(name).__name__,
                type(arguments).__name__,
            )
            continue
        calls.append(
            {"tool_name": name, "arguments": arguments, "tool_call_id": call_id}
        )
        history_calls.append(safe_tool_call_for_history(name, arguments, call_id))
    for call in getattr(response, "invalid_tool_calls", []) or []:
        if isinstance(call, dict):
            logger.warning(
                "Dropping invalid model tool call %s (error: %s); "
                "call content omitted",
                call.get("name"),
                call.get("error"),
            )
        else:
            logger.warning(
                "Dropping invalid model tool call of type %s; "
                "call content omitted",
                type(call).__name__,
            )

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
        }, False

    final_response = _message_content_to_text(getattr(response, "content", ""))
    # A whitespace-only reply (live B02: exactly "\\n") is an empty finish
    # too: it is truthy as a string, so the plain ``not final_response``
    # check let it through as a real reply and it never earned a retry.
    empty_finish = not final_response.strip()
    if empty_finish:
        final_response = "متوجه درخواست نشدم؛ لطفاً آن را واضح‌تر بیان کنید."
    final_response = await _sanitize_write_final_response(
        runtime.context["db"],
        state,
        final_response,
    )
    return {
        "messages": _append_message(state, "assistant", final_response),
        "final_response": final_response,
        "confirmation_required": False,
        "confirmation_status": "not_required",
        "route": "finish",
    }, empty_finish


async def _invoke_model_once(
    state: AgentState,
    runtime: Runtime[AgentContext],
    actor: User | None,
    model: Any,
    *,
    patient_bound: bool,
    role: str | None,
) -> tuple[dict[str, Any], bool]:
    """One model call with this actor's tools, plus response interpretation.

    The boolean is the empty-finish flag from response interpretation;
    a provider failure is never an empty finish.
    """
    try:
        response = await model.bind_tools(
            get_llm_tool_schemas(
                patient_bound=patient_bound,
                role=role,
                # The concrete account lets staff-only tool visibility honor
                # per-account allow overrides on top of the role matrix.
                actor=actor,
            )
        ).ainvoke(
            _messages_for_model(
                state,
                patient_bound=patient_bound,
                role=role,
                # Keep the prompt clock consistent with the slot logic: a
                # host/test-injected ``now`` must not disagree with the
                # system prompt's "today" line.
                now=runtime.context.get("now"),
            )
        )
    except Exception as exc:
        return await _model_failure_update(exc, state, runtime), False
    return await _interpret_model_response(response, state, runtime)


# Markers that name a reschedule (as opposed to a cancel) inside a
# cancel/reschedule request. The cancel markers are the complement of
# this set within nudges._CANCEL_RESCHEDULE_MARKERS.
_RESCHEDULE_MARKERS = ("جابه جا", "جابجا", "بنداز", "منتقل", "انتقال")


async def _server_proposal_update(
    state: AgentState,
    runtime: Runtime[AgentContext],
    actor: User | None,
) -> dict[str, Any] | None:
    """Build a confirmation proposal server-side for a stalled group-B turn.

    Live diagnosis (eval4, both models): after ``get_patient_appointments``
    the model returns an empty/whitespace reply on every re-ask — the
    act-now directive, the act-now-question stage and the empty-finish
    retry all fire and all come back empty — so the turn ends on a
    server-built list clarification instead of a confirmation proposal.
    Prompting the model again cannot fix a model that answers nothing.

    This is the deterministic last resort, run only after that recovery
    is exhausted (see ``_ask_model``). It proposes exactly what the
    model was supposed to propose, using only database facts and the
    user's own words, and it never executes anything: the returned
    update routes to the confirmation gate, which re-resolves the
    target, re-authorizes the call and issues the one-time HMAC
    confirmation exactly as for a model-proposed write. Returns None
    whenever no safe proposal exists, so the caller falls back to the
    existing clarification path:

    - ambiguous or unmatched target (live B02: two future ترمیم rows;
      live B06 with two simultaneous rows): never guess one of them;
    - unparseable reschedule destination, or a destination slot that is
      taken, off-schedule or otherwise invalid: ask instead of showing
      a confirmation the gate would refuse with a catalog error;
    - a past target, or a reschedule destination in the past: an
      explicit rejection (``_finish_clarification``), not a proposal.
      The destination's past-ness is checked before target resolution
      because it is decidable from the user's words alone — live B05
      must still be rejected explicitly even after B01 cancelled the
      shared source row.
    """
    user_text = _latest_user_text(state)
    if not user_text or _turn_had_tool_error(state):
        return None
    normalized = " ".join(normalize_text(user_text).split())
    if not any(marker in normalized for marker in _CANCEL_RESCHEDULE_MARKERS):
        return None
    tools = _turn_tool_names(state)
    if "get_patient_appointments" not in tools:
        return None
    if tools & {"cancel_appointment", "reschedule_appointment"}:
        return None
    if state.get("pending_action") is not None:
        return None

    db = runtime.context["db"]
    now = runtime.context.get("now")
    is_reschedule = any(marker in normalized for marker in _RESCHEDULE_MARKERS)
    tool_name = "reschedule_appointment" if is_reschedule else "cancel_appointment"

    destination: tuple[str, str, Any] | None = None
    if is_reschedule:
        destination = parse_reschedule_destination(
            _destination_text(tool_name, user_text), now
        )
        if destination is not None and destination[2] <= clinic_now(now):
            return _finish_clarification(state, PAST_DESTINATION_MESSAGE)

    patient_scope: list[int] | None = None
    if _is_patient_actor(actor):
        patient_scope = await linked_patient_ids(db, actor)
        if not patient_scope:
            return None
    selection = await resolve_appointment_target(
        db,
        appointment_id=None,
        user_text=_target_selection_text(tool_name, user_text),
        patient_ids=patient_scope,
        now=now,
    )
    if selection.clarification:
        if selection.clarification == PAST_TARGET_MESSAGE:
            return _finish_clarification(state, PAST_TARGET_MESSAGE)
        return None
    appointment = selection.appointment
    if appointment is None:
        return None
    if appointment.appointment_time < clinic_now(now):
        # A single past row with no explicit date reaches here; the
        # resolver only rejects past targets that name an explicit date.
        return _finish_clarification(state, PAST_TARGET_MESSAGE)

    arguments: dict[str, Any] = {}
    if is_reschedule:
        if destination is None:
            return None
        # The slot must be real, future and free for this appointment's
        # doctor/service before the user is asked to approve it.
        try:
            await validate_appointment_slot(
                db,
                appointment.doctor_id,
                appointment.service_id,
                destination[0],
                destination[1],
                exclude_appointment_id=appointment.id,
                now=now,
            )
        except AppError:
            return None
        arguments = {
            "appointment_date": destination[0],
            "appointment_time": destination[1],
        }
    return {
        "pending_action": {
            "tool_name": tool_name,
            "arguments": arguments,
            "tool_call_id": f"server-{uuid4()}",
        },
        "confirmation_required": True,
        "confirmation_status": "pending",
        "final_response": None,
        "route": "confirmation",
    }


async def _ask_model(
    state: AgentState,
    runtime: Runtime[AgentContext],
    actor: User | None,
) -> dict[str, Any]:
    """Phase 4a: call the model with the tools this actor may see.

    When the model ends the turn with plain text even though the request
    still needs a tool chain (see ``app.agent.nudges``), the turn is
    re-asked once per stall stage with a server directive appended; the
    directive never executes anything itself and every write still passes
    authorization and the confirmation gate.

    Two live-eval shapes get extra handling. An *empty* finish (no text,
    no usable call — an unparseable call through the provider proxy
    looks exactly like this) spends a stage marker on an attempt the
    model never really answered, so when a directive already fired this
    turn it is re-asked once more with that same directive instead of
    surfacing the fallback text. A whitespace-only finish counts as
    empty for the same reason. And a finish that still repeats the
    fetched appointment list after the act-now recovery is replaced by
    a server-built clarification (see ``degenerate_list_clarification``)
    rather than shown to the user verbatim. If the empty-finish retry
    also comes back empty, the turn still does not end on the bare
    fallback: ``empty_retry_clarification`` builds a server-side
    clarification from the already-fetched data instead.
    """
    model = runtime.context.get("llm") or create_chat_model()
    patient_bound = _is_patient_actor(actor)
    role = actor_role(actor)
    update, empty_finish = await _invoke_model_once(
        state, runtime, actor, model, patient_bound=patient_bound, role=role
    )
    directive_fired = False
    empty_retry_used = False
    for _ in range(4):
        if update.get("route") != "finish":
            break
        working_messages = update.get("messages") or state.get("messages", [])
        working: AgentState = {**state, "messages": working_messages}
        found = stall_directive(working, patient_bound=patient_bound)
        if found is None:
            if not (empty_finish and directive_fired and not empty_retry_used):
                break
            # stall_directive has just re-checked this turn, including
            # the tool-error gate that keeps failed-call turns (patient
            # selection, validation, authorization) out of recovery; a
            # directive could only have fired earlier with that gate
            # green, and tool results cannot change inside this loop.
            # The empty attempt therefore gets one more ask with the
            # directive already present in ``state``'s messages, without
            # spending another stage on it.
            empty_retry_used = True
            update, empty_finish = await _invoke_model_once(
                state,
                runtime,
                actor,
                model,
                patient_bound=patient_bound,
                role=role,
            )
            continue
        _stage, directive = found
        directive_fired = True
        retry_state: AgentState = {
            **working,
            "messages": [
                *working_messages,
                {"role": "system", "content": directive},
            ],
        }
        update, empty_finish = await _invoke_model_once(
            retry_state,
            runtime,
            actor,
            model,
            patient_bound=patient_bound,
            role=role,
        )
        state = retry_state
    if update.get("route") == "finish":
        # Last resort for a stalled cancel/reschedule turn: the model was
        # re-asked through every stall stage and still proposed nothing.
        # The server builds the confirmation proposal itself from the
        # fetched rows (or rejects a past target/destination explicitly);
        # when no safe proposal exists this returns None and the
        # clarification path below runs unchanged.
        proposal = await _server_proposal_update(state, runtime, actor)
        if proposal is not None:
            return proposal
        if empty_finish and empty_retry_used:
            # The extra re-ask for an empty finish also came back empty:
            # the model never really answered this turn. End on a
            # server-built clarification from the fetched data instead
            # of the bare fallback (round-3 B02/B04/B05/B06 shape).
            # ``state`` is the input of the last model call, so its
            # history carries the fetched rows and the directives but
            # not the empty reply being replaced.
            clarification = empty_retry_clarification(state)
            if clarification is not None:
                return _finish_clarification(state, clarification)
        clarification = degenerate_list_clarification(
            state, update.get("final_response") or ""
        )
        if clarification is not None:
            # ``state`` is the input of the last model call, so its
            # history carries the fetched rows and the directives but
            # not the degenerate reply being replaced.
            return _finish_clarification(state, clarification)
    return update


async def _agent_decision_impl(
    state: AgentState,
    runtime: Runtime[AgentContext],
) -> dict[str, Any]:
    """Decide the next step: confirmation, queued tool call, or the model."""
    actor = await _stable_actor(runtime)
    if state.get("pending_action") is not None:
        return await _resolve_pending_action(state, runtime, actor)
    if state.get("requested_tool"):
        return _queue_host_requested_tool(state)
    if state.get("pending_tool_calls"):
        return await _process_pending_call(state, runtime, actor)
    return await _ask_model(state, runtime, actor)


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
        if exc.code in {
            "AGENT_PROVIDER_RATE_LIMITED",
            "AGENT_PROVIDER_UNAVAILABLE",
        }:
            raise
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
        arguments = dict(action.get("arguments") or {})

        if name == "book_appointment" and not str(
            action.get("tool_call_id") or ""
        ).startswith("host-"):
            # A model-proposed booking must not contradict the service,
            # doctor, date or time the user explicitly named; the eval
            # showed the model confirming 09:00 after telling the user
            # 10:00 was free. Server-resolved option picks (host-*) are
            # already bound to the displayed option set and skip this.
            mismatch = await booking_criteria_mismatch(
                db,
                arguments=arguments,
                user_texts=_all_user_texts(state),
                now=runtime.context.get("now"),
                last_assistant_text=_latest_assistant_text(state),
            )
            if mismatch is not None:
                return _finish_clarification(state, mismatch)

        if name in {"cancel_appointment", "reschedule_appointment"}:
            # Patient callers never get to name an internal row id. The target
            # is resolved from their own linked record and explicit request
            # criteria, then stored server-side in the confirmation record.
            patient_scope: list[int] | None = None
            if _is_patient_actor(actor):
                if arguments.get("appointment_id") is not None:
                    # Reject a foreign id even if it arrived through host state
                    # rather than the model envelope.
                    await authorize_tool_call(db, actor, name, arguments)
                arguments.pop("appointment_id", None)
                patient_scope = await linked_patient_ids(db, actor)
                if not patient_scope:
                    raise AppError("PATIENT_ACCOUNT_NOT_LINKED")
            selection = await resolve_appointment_target(
                db,
                appointment_id=arguments.get("appointment_id"),
                user_text=_target_selection_text(
                    name, _latest_user_text(state)
                ),
                patient_ids=patient_scope,
                now=runtime.context.get("now"),
            )
            if selection.clarification:
                return _finish_clarification(state, selection.clarification)
            if selection.appointment is not None:
                arguments["appointment_id"] = selection.appointment.id
            action = {**action, "arguments": arguments}

        # Authorize before showing any database-derived appointment details.
        # A patient must not learn anything about somebody else's appointment.
        await _authorize_tool_call_audited(
            runtime,
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
        "pending_action": action,
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
    internal_appointment_id: int | None = None
    if definition is None:
        error = _catalog_error("COMMON_VALIDATION_ERROR")
        result = {"ok": False, "data": None, "error": error.model_dump(mode="json")}
    else:
        try:
            # Authorization choke point: identity comes only from the trusted
            # host context. Handlers re-check the same policy themselves.
            await _authorize_tool_call_audited(
                runtime,
                actor,
                name or "",
                arguments if isinstance(arguments, dict) else {},
            )
            validated = definition.input_schema.model_validate(arguments)
            # ``actor`` is a trusted host object. It is passed explicitly so a
            # handler can never fall back to a model/client identity value.
            result_object = await definition.handler(
                runtime.context["db"],
                actor=actor,
                **validated.model_dump(),
            )
            internal = result_object.internal
            if isinstance(internal.get("appointment_id"), int):
                internal_appointment_id = internal["appointment_id"]
            # ``internal`` is excluded from the model-visible payload.
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
        "last_internal_appointment_id": internal_appointment_id,
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
