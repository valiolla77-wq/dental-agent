"""Server-owned conversation history for the agent chat.

Ownership rule: every query filters by ``user_id``, so a session id alone can
never expose another user's conversation. Persistence failures surface as the
catalogued ``DATABASE_ERROR`` instead of silently dropping history.

Only user/assistant turns are stored. Tool packets, internal row ids, and
pending-write arguments never enter this table.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, desc, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.models.chat import (
    AgentConversation,
    AgentMessage,
    conversation_title_from_message,
)

logger = logging.getLogger("dental_agent.chat_history")

# Turns kept for rebuilding the model context of a new request. Tool results
# are not replayed; the model can re-call read tools when it needs facts.
MAX_CONTEXT_TURNS = 20


def _utcnow() -> datetime:
    """Naive UTC timestamp (project convention) without the deprecated utcnow()."""
    return datetime.now(UTC).replace(tzinfo=None)


class ConversationMutationError(AppError):
    def __init__(self):
        super().__init__("DATABASE_ERROR")


async def get_or_create_conversation(
    db: AsyncSession,
    *,
    user_id: int,
    session_id: str,
) -> AgentConversation:
    """Load the user's conversation for ``session_id``, creating it if needed.

    The row is written immediately (committed by the host request) so the
    conversation exists even if the model run fails, and a later reload shows
    that the chat started.
    """
    try:
        result = await db.execute(
            select(AgentConversation).where(
                AgentConversation.user_id == user_id,
                AgentConversation.session_id == session_id,
            )
        )
        conversation = result.scalar_one_or_none()
        if conversation is not None:
            return conversation
        conversation = AgentConversation(
            session_id=session_id,
            user_id=user_id,
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)
        return conversation
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "Conversation lookup failed (%s); exception details omitted",
            type(exc).__name__,
        )
        raise ConversationMutationError() from exc


async def create_conversation(
    db: AsyncSession,
    *,
    user_id: int,
    session_id: str | None = None,
    title: str | None = None,
) -> AgentConversation:
    """Explicitly start a new empty conversation for the user."""
    try:
        conversation = AgentConversation(
            session_id=session_id or uuid4().hex,
            user_id=user_id,
            title=title,
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)
        return conversation
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "Conversation create failed (%s); exception details omitted",
            type(exc).__name__,
        )
        raise ConversationMutationError() from exc


async def list_conversations(
    db: AsyncSession,
    *,
    user_id: int,
    limit: int = 50,
) -> list[tuple[AgentConversation, int]]:
    """List the user's own conversations, newest activity first."""
    try:
        counts = (
            select(
                AgentMessage.conversation_id.label("conversation_id"),
                func.count(AgentMessage.id).label("message_count"),
            )
            .group_by(AgentMessage.conversation_id)
            .subquery()
        )
        result = await db.execute(
            select(AgentConversation, counts.c.message_count)
            .outerjoin(counts, counts.c.conversation_id == AgentConversation.id)
            .where(AgentConversation.user_id == user_id)
            .order_by(desc(AgentConversation.updated_at))
            .limit(limit)
        )
        return list(result.all())
    except SQLAlchemyError as exc:
        logger.error(
            "Conversation list failed (%s); exception details omitted",
            type(exc).__name__,
        )
        raise ConversationMutationError() from exc


async def get_conversation(
    db: AsyncSession,
    *,
    user_id: int,
    session_id: str,
) -> AgentConversation:
    """Load one owned conversation; 404 for foreign or unknown sessions."""
    try:
        result = await db.execute(
            select(AgentConversation).where(
                AgentConversation.user_id == user_id,
                AgentConversation.session_id == session_id,
            )
        )
        conversation = result.scalar_one_or_none()
    except SQLAlchemyError as exc:
        logger.error(
            "Conversation load failed (%s); exception details omitted",
            type(exc).__name__,
        )
        raise ConversationMutationError() from exc
    if conversation is None:
        # Never distinguish "foreign session id" from "unknown session id":
        # both are a plain not-found for this owner's namespace.
        raise AppError("COMMON_NOT_FOUND")
    return conversation


async def list_messages(
    db: AsyncSession,
    *,
    conversation_id: int,
    limit: int | None = None,
) -> list[AgentMessage]:
    """Return the conversation's user/assistant turns in chronological order."""
    try:
        query = (
            select(AgentMessage)
            .where(AgentMessage.conversation_id == conversation_id)
            .order_by(AgentMessage.id)
        )
        if limit is not None:
            # Select the newest ``limit`` rows in reverse, then re-ascend so
            # the returned order stays chronological.
            newest = (
                select(AgentMessage.id)
                .where(AgentMessage.conversation_id == conversation_id)
                .order_by(desc(AgentMessage.id))
                .limit(limit)
                .subquery()
            )
            query = (
                select(AgentMessage)
                .where(AgentMessage.id.in_(select(newest.c.id)))
                .order_by(AgentMessage.id)
            )
        result = await db.execute(query)
        return list(result.scalars().all())
    except SQLAlchemyError as exc:
        logger.error(
            "Message list failed (%s); exception details omitted",
            type(exc).__name__,
        )
        raise ConversationMutationError() from exc


async def reload_conversation(
    db: AsyncSession,
    conversation: AgentConversation,
) -> AgentConversation | None:
    """Re-load owned conversation state after a graph run.

    A failed tool rolls the session back, which expires every loaded ORM
    instance — including the conversation loaded before the run. Mutating an
    expired instance fails, so callers re-attach to a fresh SELECT row. The
    conversation cannot silently switch owner: the reload filters by its
    primary key AND the row's persisted user_id.
    """
    try:
        await db.refresh(conversation)
        return conversation
    except Exception:  # noqa: BLE001 - refresh may fail on a rolled-back row
        try:
            await db.rollback()
            result = await db.execute(
                select(AgentConversation).where(
                    AgentConversation.id == conversation.id,
                    AgentConversation.user_id == conversation.user_id,
                )
            )
            return result.scalar_one_or_none()
        except AppError:
            raise
        except SQLAlchemyError:
            await db.rollback()
            logger.error(
                "Conversation reload failed; turn not persisted; details omitted"
            )
            return None
        except Exception:  # noqa: BLE001 - never break the reply over reload
            await db.rollback()
            logger.error(
                "Conversation reload failed unexpectedly; turn not persisted"
            )
            return None


async def append_turn(
    db: AsyncSession,
    *,
    conversation: AgentConversation,
    user_text: str,
    assistant_text: str,
    assistant_available: bool,
) -> None:
    """Persist one user turn and, when produced, the assistant reply.

    ``assistant_available=False`` records that the turn was asked but the
    reply could not be retrieved, so a later reload never fabricates an
    assistant message for an answer that never happened.
    """
    try:
        prepared_user = " ".join(user_text.split())[:4000].strip()
        if not prepared_user:
            raise AppError("COMMON_VALIDATION_ERROR")
        db.add(
            AgentMessage(
                conversation_id=conversation.id,
                role="user",
                content=prepared_user,
                created_at=_utcnow(),
            )
        )
        if assistant_available and isinstance(assistant_text, str):
            prepared_assistant = assistant_text[:4000].strip()
            if prepared_assistant:
                db.add(
                    AgentMessage(
                        conversation_id=conversation.id,
                        role="assistant",
                        content=prepared_assistant,
                        created_at=_utcnow(),
                    )
                )
        if conversation.title is None:
            conversation.title = conversation_title_from_message(prepared_user)
        conversation.updated_at = _utcnow()
        await db.commit()
    except AppError:
        await db.rollback()
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "Turn persistence failed (%s); exception details omitted",
            type(exc).__name__,
        )
        raise ConversationMutationError() from exc


async def save_active_options(
    db: AsyncSession,
    *,
    conversation: AgentConversation,
    kind: str | None,
    payload: dict | None,
) -> None:
    """Replace the conversation's active selectable options.

    Options may be cleared (``kind=None``) after a booking confirmation so a
    stale «گزینه ۲» cannot select a removed slot again.
    """
    try:
        conversation.options_kind = kind
        conversation.options_payload = payload
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "Options persistence failed (%s); exception details omitted",
            type(exc).__name__,
        )
        raise ConversationMutationError() from exc


async def delete_conversation(
    db: AsyncSession,
    *,
    user_id: int,
    session_id: str,
) -> None:
    """Delete an owned conversation and its messages; fail closed otherwise."""
    try:
        result = await db.execute(
            select(AgentConversation.id).where(
                AgentConversation.user_id == user_id,
                AgentConversation.session_id == session_id,
            )
        )
        conversation_id = result.scalar_one_or_none()
        if conversation_id is None:
            raise AppError("COMMON_NOT_FOUND")
        await db.execute(
            delete(AgentMessage).where(
                AgentMessage.conversation_id == conversation_id
            )
        )
        await db.execute(
            delete(AgentConversation).where(
                AgentConversation.id == conversation_id
            )
        )
        await db.commit()
    except AppError:
        await db.rollback()
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "Conversation delete failed (%s); exception details omitted",
            type(exc).__name__,
        )
        raise ConversationMutationError() from exc


def context_from_messages(
    messages: list[AgentMessage],
) -> list[dict[str, str]]:
    """Build model context turns from persisted, verified-owned rows."""
    context: list[dict[str, str]] = []
    for row in messages:
        role = row.role
        if role not in ("user", "assistant"):
            continue
        content = (row.content or "").strip()
        if not content:
            continue
        context.append({"role": role, "content": content})
    return context[-MAX_CONTEXT_TURNS:]
