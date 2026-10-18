"""LangGraph orchestration for chat decisions and allowlisted tools."""

import json
import logging
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
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.confirmations import ConfirmationDecision, confirmation_store
from app.agent.llm import ToolCallingChatModel, create_chat_model
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.registry import TOOL_REGISTRY, ToolDefinition, get_llm_tool_schemas
from app.agent.state import AgentState, ConversationMessage, PendingAction, PendingToolCall
from app.agent_tools.schemas import AgentToolError
from app.auth.permissions import authorize_tool_call
from app.errors import ERROR_CATALOG, AppError
from app.models.user import User


logger = logging.getLogger("dental_agent.agent")


class AgentContext(TypedDict, total=False):
    """Trusted per-invoke inputs from the host: dependencies, session identity,
    the authenticated actor, and the confirmation decision. Nothing here
    round-trips through AgentState."""

    db: AsyncSession
    llm: ToolCallingChatModel
    session_id: str | None
    actor: User | None
    confirmation: ConfirmationDecision


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


def _messages_for_model(state: AgentState) -> list[BaseMessage]:
    messages: list[BaseMessage] = [SystemMessage(content=SYSTEM_PROMPT)]
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


def _confirmation_prompt(action: PendingAction) -> str:
    name = action.get("tool_name")
    args = action.get("arguments") or {}
    labels = {
        "book_appointment": "ثبت نوبت",
        "cancel_appointment": "لغو نوبت",
        "reschedule_appointment": "جابه‌جایی نوبت",
    }
    summary = labels.get(name, "اجرای عملیات")
    if name == "book_appointment":
        patient = args.get("full_name") or args.get("patient_id") or "بیمار مشخص‌شده"
        summary += (
            f" برای {patient} با پزشک {args.get('doctor_id', 'نامشخص')}"
            f" و خدمت {args.get('service_id', 'نامشخص')}"
            f" در تاریخ {args.get('appointment_date', 'نامشخص')}"
            f" ساعت {args.get('appointment_time', 'نامشخص')}"
        )
    elif name == "reschedule_appointment":
        summary += (
            f" نوبت {args.get('appointment_id', 'نامشخص')} به تاریخ "
            f"{args.get('appointment_date', 'نامشخص')} ساعت "
            f"{args.get('appointment_time', 'نامشخص')}"
            f" با پزشک {args.get('doctor_id', 'پزشک ثبت‌شده')}"
            f" و خدمت {args.get('service_id', 'خدمت ثبت‌شده')}"
        )
    elif name == "cancel_appointment":
        summary += f" شماره {args.get('appointment_id', 'نامشخص')}"
    return f"برای {summary} تأیید می‌کنید؟"


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


async def _agent_decision_node(
    state: AgentState,
    runtime: Runtime[AgentContext],
) -> dict[str, Any]:
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
        actor = runtime.context.get("actor")
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
    try:
        response = await model.bind_tools(get_llm_tool_schemas()).ainvoke(
            _messages_for_model(state)
        )
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


async def _confirmation_node(
    state: AgentState,
    runtime: Runtime[AgentContext],
) -> dict[str, Any]:
    action = state.get("pending_action")
    confirmation_token = None
    actor = runtime.context.get("actor")
    user_id = actor.id if actor is not None else None
    if isinstance(action, dict):
        definition = TOOL_REGISTRY.get(action.get("tool_name") or "")
        if definition is not None and definition.operation == "write":
            record = await confirmation_store.issue(
                runtime.context["db"],
                session_id=runtime.context.get("session_id"),
                user_id=user_id,
                tool_name=action.get("tool_name") or "",
                arguments=action.get("arguments") or {},
                tool_call_id=action.get("tool_call_id") or str(uuid4()),
            )
            confirmation_token = record.token
    prompt = (
        _confirmation_prompt(action)
        if isinstance(action, dict)
        else "برای این عملیات تأیید شما لازم است."
    )
    return {
        "confirmation_required": True,
        "confirmation_status": "pending",
        "confirmation_token": confirmation_token,
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
    if definition is None:
        error = _catalog_error("COMMON_VALIDATION_ERROR")
        result = {"ok": False, "data": None, "error": error.model_dump(mode="json")}
    else:
        try:
            # Authorization choke point: identity comes only from the trusted
            # host context. No handler runs without a permitted actor.
            await authorize_tool_call(
                runtime.context["db"],
                runtime.context.get("actor"),
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
