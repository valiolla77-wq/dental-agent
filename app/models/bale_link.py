"""Bale messenger chat ↔ patient phone bindings for OTP delivery.

One row per linked chat. The phone is only ever taken from a ``contact``
update produced by Bale's ``request_contact`` reply-keyboard button, which
Bale fills with the phone number the sender's own Bale account is registered
with — a chat can therefore only claim the number it genuinely owns (never a
number typed as plain text).
"""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BaleChatLink(Base):
    __tablename__ = "bale_chat_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Clinic-side phone in the canonical ``09xxxxxxxxx`` form; unique so one
    # phone maps to exactly one chat and codes can never fan out to two chats.
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    # Bale numeric chat id, stored as text; unique so one chat cannot hold
    # several phones (re-linking replaces the previous row instead).
    chat_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # Sender display name from Bale, for support/debugging only (never shown
    # to other users).
    first_name: Mapped[str | None] = mapped_column(String(120), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
