"""Minimal, serializable state shared by the single-agent graph nodes."""

from typing import Any, Literal, TypedDict

from app.agent_tools.schemas import AgentToolError


class ConversationMessage(TypedDict, total=False):
    role: Literal["user", "assistant", "system", "tool"]
    content: Any
    tool_calls: list[dict[str, Any]]
    tool_call_id: str
    name: str


class PendingAction(TypedDict):
    tool_name: str
    arguments: dict[str, Any]
    tool_call_id: str


class PendingToolCall(TypedDict):
    tool_name: str
    arguments: dict[str, Any]
    tool_call_id: str


class AgentState(TypedDict, total=False):
    messages: list[ConversationMessage]
    intent: str | None
    patient_id: int | None
    service_id: int | None
    doctor_id: int | None
    appointment_id: int | None
    appointment_date: str | None
    appointment_time: str | None
    requested_tool: str | None
    tool_arguments: dict[str, Any]
    selected_tool: str | None
    selected_tool_arguments: dict[str, Any]
    selected_tool_call_id: str | None
    pending_action: PendingAction | None
    pending_tool_calls: list[PendingToolCall]
    last_tool_result: dict[str, Any] | None
    last_tool_error: AgentToolError | None
    confirmation_required: bool
    confirmation_status: Literal["not_required", "pending", "approved", "rejected"]
    confirmation_token: str | None
    confirmation_prompt: str | None
    final_response: str | None
    route: Literal["continue", "execute_tool", "confirmation", "finish"]


def create_initial_state(
    *,
    messages: list[ConversationMessage] | None = None,
    intent: str | None = None,
    patient_id: int | None = None,
    service_id: int | None = None,
    doctor_id: int | None = None,
    appointment_id: int | None = None,
    appointment_date: str | None = None,
    appointment_time: str | None = None,
    requested_tool: str | None = None,
    tool_arguments: dict[str, Any] | None = None,
) -> AgentState:
    """Create a fresh state; callers own conversation/session lifecycle."""
    return AgentState(
        messages=list(messages or []),
        intent=intent,
        patient_id=patient_id,
        service_id=service_id,
        doctor_id=doctor_id,
        appointment_id=appointment_id,
        appointment_date=appointment_date,
        appointment_time=appointment_time,
        requested_tool=requested_tool,
        tool_arguments=dict(tool_arguments or {}),
        selected_tool=None,
        selected_tool_arguments={},
        selected_tool_call_id=None,
        pending_action=None,
        pending_tool_calls=[],
        last_tool_result=None,
        last_tool_error=None,
        confirmation_required=False,
        confirmation_status="not_required",
        confirmation_token=None,
        confirmation_prompt=None,
        final_response=None,
        route="finish",
    )
