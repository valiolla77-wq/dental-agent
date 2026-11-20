"""LangGraph orchestration for chat decisions and allowlisted tools."""

import json
import logging
from typing import Any
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from pydantic import ValidationError

from app.agent.appointment_selection import (
    resolve_appointment_target,
)
from app.agent.confirmation_text import _describe_action, _target_selection_text
from app.agent.confirmations import confirmation_store
from app.agent.context import AGENT_RECURSION_LIMIT, MAX_AGENT_STEPS, AgentContext
from app.agent.llm import create_chat_model
from app.agent.messages import (
    _append_message,
    _latest_user_text,
    _message_content_to_text,
    _messages_for_model,
    safe_tool_call_for_history,
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
) -> dict[str, Any]:
    """Phase 4b: queue the model's tool calls, or finish with its text reply."""
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
        history_calls.append(safe_tool_call_for_history(name, arguments, call_id))

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
    }


async def _ask_model(
    state: AgentState,
    runtime: Runtime[AgentContext],
    actor: User | None,
) -> dict[str, Any]:
    """Phase 4a: call the model with the tools this actor may see."""
    model = runtime.context.get("llm") or create_chat_model()
    patient_bound = _is_patient_actor(actor)
    role = actor_role(actor)
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
        return await _model_failure_update(exc, state, runtime)
    return await _interpret_model_response(response, state, runtime)


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
