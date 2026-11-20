"""Message-list helpers and the model-safe view of tool calls."""

from datetime import datetime
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.agent.prompts import build_system_prompt
from app.agent.state import AgentState, ConversationMessage


def _append_message(
    state: AgentState,
    role: str,
    content: Any,
    **metadata: Any,
) -> list[ConversationMessage]:
    message: ConversationMessage = {"role": role, "content": content, **metadata}  # type: ignore[typeddict-item]
    return [*state.get("messages", []), message]


def _latest_user_text(state: AgentState) -> str:
    """Return the latest user-visible request text from trusted graph state."""
    for item in reversed(state.get("messages", [])):
        if item.get("role") == "user":
            content = item.get("content", "")
            return _message_content_to_text(content)
    return ""


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        )
    return str(content) if content is not None else ""


def _messages_for_model(
    state: AgentState,
    *,
    patient_bound: bool = False,
    now: datetime | None = None,
    role: str | None = None,
) -> list[BaseMessage]:
    messages: list[BaseMessage] = [
        SystemMessage(
            content=build_system_prompt(
                now,
                patient_bound=patient_bound,
                role=role,
            )
        )
    ]
    for item in state.get("messages", []):
        item_role = item["role"]
        content = item.get("content", "")
        if item_role == "user":
            messages.append(HumanMessage(content=content))
        elif item_role == "system":
            messages.append(SystemMessage(content=content))
        elif item_role == "assistant":
            tool_calls = item.get("tool_calls", [])
            messages.append(
                AIMessage(content=content, tool_calls=tool_calls)
                if tool_calls
                else AIMessage(content=content)
            )
        elif item_role == "tool":
            messages.append(
                ToolMessage(
                    content=content,
                    tool_call_id=item["tool_call_id"],
                    name=item.get("name"),
                )
            )
    return messages


# Arguments needed for execution but never replayed into model history. This
# includes patient PII, internal row ids, and the server-resolved target.
_MODEL_HIDDEN_ARGUMENTS = frozenset(
    {
        "national_id",
        "full_name",
        "phone",
        "reason",
        "patient_id",
        "appointment_id",
    }
)


def safe_tool_call_for_history(
    name: str,
    arguments: dict[str, Any],
    call_id: str,
) -> dict[str, Any]:
    """Build an assistant tool-call message without internal/PII arguments."""
    safe_arguments = {
        key: value
        for key, value in arguments.items()
        if key not in _MODEL_HIDDEN_ARGUMENTS
    }
    return {"name": name, "args": safe_arguments, "id": call_id, "type": "tool_call"}
