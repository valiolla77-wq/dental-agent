"""Authenticated chat endpoint for the LangGraph dental assistant.

Chat turns are single-shot (no conversation history is persisted), but a
pending write confirmation is persisted in ``agent_confirmations``. The
client receives a ``session_id`` on every response and must send the same
value with the confirmation decision. Session ownership is always the
server-side ``(user_id, session_id)`` pair; the client cannot name the tool,
its arguments, or another user.
"""

from __future__ import annotations

import logging
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import agent_graph, create_initial_state
from app.agent.confirmations import confirmation_store
from app.agent.graph import AGENT_RECURSION_LIMIT
from app.agent.llm import ToolCallingChatModel, create_chat_model, load_llm_config
from app.agent_tools.schemas import NearestAppointmentsToolData
from app.auth.dependencies import get_current_user
from app.database import get_db
from app.errors import AppError
from app.models.user import User

logger = logging.getLogger("dental_agent.agent_chat")

router = APIRouter(
    prefix="/agent",
    tags=["Agent"],
)


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
    session_id: str
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


@router.post("/chat", response_model=ChatResponse)
async def agent_chat(
    payload: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    llm: ToolCallingChatModel = Depends(get_chat_llm),
):
    """Run one assistant turn for the authenticated user."""
    if payload.confirmation is not None and payload.session_id is None:
        # Never silently start a fresh session for an approval: that would
        # hide the fact that the original pending action cannot be recovered.
        raise AppError("AGENT_CONFIRMATION_INVALID")

    session_id = payload.session_id or uuid4().hex
    history = [
        {"role": item.role, "content": item.content}
        for item in payload.history
    ]
    state = create_initial_state(
        messages=[
            *history,
            {"role": "user", "content": payload.message},
        ]
    )

    if payload.confirmation is not None:
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
                    {
                        "name": record.tool_name,
                        "args": dict(record.arguments),
                        "id": record.tool_call_id,
                        "type": "tool_call",
                    }
                ],
            }
        )

    context: dict = {
        "db": db,
        "llm": llm,
        "session_id": session_id,
        "actor": current_user,
    }
    if payload.confirmation is not None:
        context["confirmation"] = payload.confirmation.model_dump()

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
        return ChatResponse(
            reply=(
                "درخواست بیش از حد پیچیده شد و برای جلوگیری از اجرای ناقص "
                "متوقف شد. لطفاً آن را کوتاه‌تر و مشخص‌تر بنویسید."
            ),
            confirmation_required=False,
            suggested_appointments=[],
            slots=[],
            session_id=session_id,
            request_id=getattr(request.state, "request_id", None),
        )

    suggested = _suggested_appointments(result)
    return ChatResponse(
        reply=result.get("final_response") or "",
        confirmation_required=bool(result.get("confirmation_required")),
        confirmation_prompt=result.get("confirmation_prompt"),
        confirmation_token=result.get("confirmation_token"),
        suggested_appointments=suggested,
        slots=suggested,
        session_id=session_id,
        request_id=getattr(request.state, "request_id", None),
    )
