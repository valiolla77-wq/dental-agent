"""Persistent agent conversations and messages.

Every conversation is owned by exactly one user account and identified by a
stable ``session_id``. Message rows are the authoritative history for the
model and the client; nothing about ownership is ever taken from the client.
Sensitive write-tool arguments are not stored here (pending writes live in
``agent_confirmations``).
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AgentConversation(Base):
    __tablename__ = "agent_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Known to the client for continuity, but always scoped by owner in queries.
    session_id: Mapped[str] = mapped_column(String(120), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # Server-generated from the first real user message; never client-trusted.
    title: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # The active selectable-option set of the conversation's last turn.
    # Persisted so a numeric reply such as «۲» or «گزینه 2» resolves against
    # the options that were actually displayed, even after a page reload.
    options_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    options_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Which saved patient this conversation is currently booking for. It is
    # set only when the authenticated account owns the selected record, and
    # reset naturally by starting a new conversation.
    selected_patient_id: Mapped[int | None] = mapped_column(
        ForeignKey("patients.id"),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        # A session_id is unique per owner; the same value sent by another
        # user maps to their own (or no) conversation, never to this one.
        Index(
            "uq_agent_conversations_user_session",
            "user_id",
            "session_id",
            unique=True,
        ),
        Index("ix_agent_conversations_user_updated", "user_id", "updated_at"),
    )


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("agent_conversations.id"),
        index=True,
    )
    # Only "user" and "assistant" turns are persisted; tool payloads are not.
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


def conversation_title_from_message(message: str) -> str | None:
    """Derive a short Persian title from the first real user message."""
    compact = " ".join(message.split())
    if not compact:
        return None
    return compact[:140]
