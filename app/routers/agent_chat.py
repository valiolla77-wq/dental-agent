"""Authenticated chat endpoint for the LangGraph dental assistant.

Single-turn per request: no chat history is persisted. Human approval of
write operations flows through the same server-side confirmation mechanism
(allows through the optional ``confirmation`` payload field).
"""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import agent_graph, create_initial_state
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
    token: str
    decision: Literal["approved", "rejected"]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=120)
    confirmation: ChatConfirmation | None = None


class ChatResponse(BaseModel):
    reply: str
    confirmation_required: bool
    confirmation_prompt: str | None = None
    confirmation_token: str | None = None
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
    session_id = f"user-{current_user.id}:" + (
        payload.session_id or str(uuid4())
    )
    context: dict = {
        "db": db,
        "llm": llm,
        "session_id": session_id,
        "actor": current_user,
    }
    if payload.confirmation is not None:
        context["confirmation"] = payload.confirmation.model_dump()
    state = create_initial_state(
        messages=[{"role": "user", "content": payload.message}]
    )
    result = await agent_graph.ainvoke(state, context=context)
    return ChatResponse(
        reply=result.get("final_response") or "",
        confirmation_required=bool(result.get("confirmation_required")),
        confirmation_prompt=result.get("confirmation_prompt"),
        confirmation_token=result.get("confirmation_token"),
        request_id=getattr(request.state, "request_id", None),
    )