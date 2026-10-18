"""Authenticated chat endpoint for the LangGraph dental assistant.

Chat turns are single-shot (no conversation history is persisted), but a
pending write confirmation is persisted in ``agent_confirmations``. The
client receives a ``session_id`` on every response and must send the same
value with the confirmation decision. Session ownership is always the
server-side ``(user_id, session_id)`` pair; the client cannot name the tool,
its arguments, or another user.
"""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import agent_graph, create_initial_state
from app.agent.confirmations import confirmation_store
from app.agent.llm import ToolCallingChatModel, create_chat_model, load_llm_config
from app.auth.dependencies import get_current_user
from app.database import get_db
from app.errors import AppError
from app.models.user import User

router = APIRouter(
    prefix="/agent",
    tags=["Agent"],
)


class ChatConfirmation(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    decision: Literal["approved", "rejected"]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    confirmation: ChatConfirmation | None = None


class ChatResponse(BaseModel):
    reply: str
    confirmation_required: bool
    confirmation_prompt: str | None = None
    confirmation_token: str | None = None
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
    state = create_initial_state(
        messages=[{"role": "user", "content": payload.message}]
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

    result = await agent_graph.ainvoke(state, context=context)
    return ChatResponse(
        reply=result.get("final_response") or "",
        confirmation_required=bool(result.get("confirmation_required")),
        confirmation_prompt=result.get("confirmation_prompt"),
        confirmation_token=result.get("confirmation_token"),
        session_id=session_id,
        request_id=getattr(request.state, "request_id", None),
    )
