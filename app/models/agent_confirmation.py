"""Persisted confirmation records for agent write operations.

Only a hash of the confirmation token is stored. The pending operation
(tool name, exact arguments, tool call id) lives server-side and is keyed by
the authenticated user and session, never by client-supplied operation data.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AgentConfirmation(Base):
    __tablename__ = "agent_confirmations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    session_id: Mapped[str] = mapped_column(String(120))
    tool_name: Mapped[str] = mapped_column(String(64))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON)
    tool_call_id: Mapped[str] = mapped_column(String(200))
    token_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision: Mapped[str | None] = mapped_column(String(16), nullable=True)

    __table_args__ = (
        # One live write proposal per authenticated user and session.
        UniqueConstraint(
            "user_id",
            "session_id",
            name="uq_agent_confirmations_user_session",
        ),
        Index(
            "ix_agent_confirmations_lookup",
            "user_id",
            "session_id",
            "token_hash",
        ),
        Index("ix_agent_confirmations_expires_at", "expires_at"),
    )
