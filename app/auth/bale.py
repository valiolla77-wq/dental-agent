"""Bale messenger bot integration for patient OTP delivery.

Bale (bale.ai) exposes a Telegram-style bot API over HTTPS:
``https://tapi.bale.ai/bot<token>/<Method>`` with JSON bodies and an
``{ok, result}`` envelope. This module provides the delivery channel behind
``OTP_PROVIDER=bale``:

- ``BaleBotClient``: a small async HTTP client (``getMe``, ``getUpdates``,
  ``sendMessage``) with finite timeouts. The token is never logged and all
  vendor failures collapse into the catalogued generic error.
- Contact-based linking: the bot accepts a phone number *only* when it
  arrives as a ``contact`` update produced by Bale's ``request_contact``
  reply-keyboard button, which Bale fills with the phone the sender's own
  Bale account is registered with. Plain-typed numbers are deliberately
  rejected so one chat can never claim someone else's phone.
- ``run_bale_poller``: a long-polling asyncio task started by the app
  lifespan. Fresh updates are processed (link / unlink / help replies);
  a bounded backlog is honoured on startup and anything older is skipped.

Security notes:
- OTP codes travel only through :meth:`BaleProvider.send` to the chat linked
  to the requesting phone; command replies never contain codes.
- An unlinked phone raises the generic delivery error, the code is burned by
  the OTP service, and the HTTP response stays uniform — the API cannot be
  used to discover whether a phone is linked.
- The poller is best-effort infrastructure: every failure is caught, logged
  without vendor detail, and retried with backoff; it can never take the
  web app down.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Any

import httpx

from app.errors import AppError

logger = logging.getLogger(__name__)

BALE_DEFAULT_BASE_URL = "https://tapi.bale.ai"
# Short per-call budget; the long-poll call gets the poll timeout on top.
_HTTP_TIMEOUT_SECONDS = 10.0

_GENERIC_FAILURE = "COMMON_SERVICE_UNAVAILABLE"

# Backlog older than this is skipped at poller startup (replays of months-old
# ``/start`` or contact messages would only confuse patients).
_MAX_BACKLOG_AGE_SECONDS = 600.0
# Poller restart backoff (exponential, capped).
_POLL_BACKOFF_START_SECONDS = 5.0
_POLL_BACKOFF_MAX_SECONDS = 60.0


def bale_bot_token() -> str:
    """Bot token from the environment (empty when unset)."""
    return os.getenv("BALE_BOT_TOKEN", "").strip()


def bale_base_url() -> str:
    """API base URL; overridable for tests, never logged with the token."""
    return os.getenv("BALE_API_BASE", BALE_DEFAULT_BASE_URL).strip().rstrip("/")


def bale_poll_timeout_seconds() -> int:
    try:
        return max(0, int(os.getenv("BALE_POLL_TIMEOUT_SECONDS", "25")))
    except ValueError:
        return 25


def bale_provider_configured() -> bool:
    """True when the Bale channel is selected and has a token."""
    from app.auth.sms import provider_name

    return provider_name() == "bale" and bool(bale_bot_token())


def bale_poller_enabled() -> bool:
    """Kill-switch for the in-process poller (default on)."""
    return os.getenv("BALE_POLLER_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }


class BaleApiError(Exception):
    """Raised for any Bale API failure; carries no vendor secrets."""

    def __init__(self, code: int | None = None) -> None:
        self.code = code
        super().__init__(f"bale api error (code={code})")


def normalize_ir_mobile(raw: str | None) -> str | None:
    """Canonical ``09xxxxxxxxx`` form, or ``None`` when not an Iranian mobile.

    Accepts ``0912...``, ``912...``, ``+98912...`` and ``0098912...`` and is
    shared by the bot's contact handler and the delivery lookup so both sides
    of the link always agree on the stored format.
    """
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("0098"):
        digits = digits[4:]
    elif digits.startswith("98") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 10 or not digits.startswith("9"):
        return None
    return f"0{digits}"


class BaleBotClient:
    """Minimal async Bale Bot API client (JSON POST, fail-closed).

    ``token``/``base_url``/``transport`` default to the environment; tests
    inject an ``httpx`` transport so no real network call ever happens.
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = (token if token is not None else bale_bot_token()).strip()
        self._base_url = (base_url if base_url is not None else bale_base_url()).rstrip("/")
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self._token)

    def _url(self, method: str) -> str:
        return f"{self._base_url}/bot{self._token}/{method}"

    async def call(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float = _HTTP_TIMEOUT_SECONDS,
    ) -> Any:
        if not self._token:
            raise BaleApiError()
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout),
                transport=self._transport,
            ) as client:
                response = await client.post(self._url(method), json=payload or {})
        except httpx.HTTPError:
            raise BaleApiError() from None
        try:
            data = response.json()
        except ValueError:
            raise BaleApiError(response.status_code) from None
        if response.status_code != 200 or not isinstance(data, dict) or not data.get("ok"):
            raise BaleApiError(response.status_code)
        return data.get("result")

    async def get_me(self) -> dict[str, Any]:
        result = await self.call("getMe")
        return result if isinstance(result, dict) else {}

    async def get_updates(self, offset: int | None, timeout: int = 0) -> list[dict[str, Any]]:
        result = await self.call(
            "getUpdates",
            {"offset": offset, "timeout": max(0, int(timeout))},
            timeout=_HTTP_TIMEOUT_SECONDS + max(0, int(timeout)),
        )
        return [item for item in (result or []) if isinstance(item, dict)]

    async def send_message(
        self,
        chat_id: str | int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {"chat_id": str(chat_id), "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        await self.call("sendMessage", payload)


# Bale shares this fork of Telegram's reply keyboard, so the contact button
# must stay a single obvious action; a one-row keyboard cannot be misread.
_CONTACT_KEYBOARD: dict[str, Any] = {
    "keyboard": [
        [{"text": "اشتراک شماره تماس", "request_contact": True}],
    ],
    "resize_keyboard": True,
    "one_time_keyboard": False,
}

_WELCOME_TEXT = (
    "سلام 👋\n"
    "این بات، کد ورود (رمز یک‌بارمصرف) پرتال بیماران کلینیک را برای شما ارسال می‌کند.\n\n"
    "برای اتصال شماره تلفن، روی دکمه «اشتراک شماره تماس» بزنید؛ سپس در سایت کلینیک "
    "کد ورود را درخواست کنید تا همین‌جا دریافت شود."
)
_LINKED_TEXT = (
    "شماره {phone} به حساب بله شما متصل شد ✅\n"
    "حالا در سایت کلینیک، در بخش ورود با کد یک‌بارمصرف، شماره خود را وارد و کد را درخواست کنید."
)
_RELINKED_TEXT = (
    "شماره {phone} به‌روزرسانی و به همین گفت‌وگو متصل شد ✅\nکد ورود بعدی به همین گفت‌وگو ارسال می‌شود."
)
_INVALID_PHONE_TEXT = (
    "شماره‌ای که اشتراک گذاشته شده معتبر نیست ⚠️\n"
    "لطفاً با شماره تلفن همراه ایران (مثل ۰۹۱۲...) که حساب بله شما با آن ساخته شده دوباره تلاش کنید."
)
_UNLINKED_TEXT = "اتصال این گفت‌وگو حذف شد. برای اتصال دوباره، روی دکمه «اشتراک شماره تماس» بزنید."
_HINT_TEXT = (
    "برای اتصال شماره، لطفاً فقط از دکمه «اشتراک شماره تماس» استفاده کنید؛ "
    "شماره را تایپ نکنید تا از اتصال شماره دیگران جلوگیری شود."
)


async def get_chat_id_for_phone(db: Any, phone: str) -> str | None:
    """Linked chat id for a phone, tolerant of the caller's input format."""
    from sqlalchemy import select

    from app.models.bale_link import BaleChatLink

    candidates: list[str] = []
    stripped = (phone or "").strip()
    if stripped:
        candidates.append(stripped)
    normalized = normalize_ir_mobile(stripped)
    if normalized and normalized not in candidates:
        candidates.append(normalized)
    if not candidates:
        return None
    result = await db.execute(
        select(BaleChatLink.chat_id).where(BaleChatLink.phone.in_(candidates))
    )
    return result.scalar_one_or_none()


async def link_phone(db: Any, phone: str, chat_id: str, first_name: str | None = None) -> bool:
    """Bind one chat to one phone (1:1); return True when the row is new.

    Both directions are enforced: re-linking the same chat to a new phone or
    the same phone to a new chat replaces the previous rows, so a code can
    never race to two chats or two phones at once.
    """
    from datetime import UTC, datetime

    from sqlalchemy import delete, select

    from app.models.bale_link import BaleChatLink

    now = datetime.now(UTC).replace(tzinfo=None)
    existing_phone = (
        await db.execute(select(BaleChatLink).where(BaleChatLink.phone == phone))
    ).scalar_one_or_none()
    is_new = existing_phone is None

    # Drop any other row holding this chat first (unique constraint guard),
    # then update the phone row in place or insert a fresh one.
    await db.execute(
        delete(BaleChatLink).where(
            BaleChatLink.chat_id == chat_id,
            BaleChatLink.phone != phone,
        )
    )
    if existing_phone is not None:
        existing_phone.chat_id = chat_id
        existing_phone.first_name = first_name
        existing_phone.updated_at = now
    else:
        db.add(
            BaleChatLink(
                phone=phone,
                chat_id=chat_id,
                first_name=first_name,
                created_at=now,
                updated_at=now,
            )
        )
    await db.commit()
    return is_new


async def unlink_chat(db: Any, chat_id: str) -> bool:
    from sqlalchemy import delete, select

    from app.models.bale_link import BaleChatLink

    existing = (
        await db.execute(select(BaleChatLink).where(BaleChatLink.chat_id == chat_id))
    ).scalar_one_or_none()
    if existing is None:
        return False
    await db.execute(delete(BaleChatLink).where(BaleChatLink.chat_id == chat_id))
    await db.commit()
    return True


def _message_of(update: dict[str, Any]) -> dict[str, Any] | None:
    message = update.get("message")
    return message if isinstance(message, dict) else None


def _update_age_seconds(update: dict[str, Any]) -> float | None:
    """Age of the update from ``message.date`` (epoch seconds), if present."""
    message = _message_of(update)
    if not message:
        return None
    try:
        sent_at = float(message.get("date"))
    except (TypeError, ValueError):
        return None
    return max(0.0, time.time() - sent_at)


async def process_update(update: dict[str, Any], client: BaleBotClient | None = None) -> None:
    """Handle one bot update. Best-effort: never raises to the poller loop.

    Only ``message`` updates from private chats are acted upon; everything
    else is ignored silently.
    """
    from app.database import SessionLocal

    bot = client if client is not None else BaleBotClient()
    message = _message_of(update)
    if not message:
        return
    chat = message.get("chat")
    if not isinstance(chat, dict) or chat.get("id") is None:
        return
    chat_id = str(chat["id"])
    contact = message.get("contact") if isinstance(message.get("contact"), dict) else None
    text = message.get("text") if isinstance(message.get("text"), str) else ""
    sender_name = (message.get("from") or {}).get("first_name")
    sender_name = sender_name if isinstance(sender_name, str) else None

    try:
        if contact is not None:
            phone = normalize_ir_mobile(str(contact.get("phone_number") or ""))
            if phone is None:
                await bot.send_message(chat_id, _INVALID_PHONE_TEXT)
                return
            async with SessionLocal() as db:
                was_new = await link_phone(db, phone, chat_id, sender_name)
            template = _LINKED_TEXT if was_new else _RELINKED_TEXT
            await bot.send_message(chat_id, template.format(phone=phone))
            return

        command = text.strip().split("@", 1)[0].lower()
        if command in {"/start", "/help"}:
            await bot.send_message(chat_id, _WELCOME_TEXT, reply_markup=_CONTACT_KEYBOARD)
            return
        if command == "/unlink":
            async with SessionLocal() as db:
                removed = await unlink_chat(db, chat_id)
            await bot.send_message(
                chat_id,
                _UNLINKED_TEXT if removed else _WELCOME_TEXT,
                reply_markup=None if removed else _CONTACT_KEYBOARD,
            )
            return
        # Any other text (including a typed phone number) must never create
        # a link; nudge the user to the contact button instead.
        await bot.send_message(chat_id, _HINT_TEXT, reply_markup=_CONTACT_KEYBOARD)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("Bale update could not be processed")


class BaleProvider:
    """``SmsProvider`` implementation delivering OTP through the Bale bot.

    Construction fails closed when no token is configured, matching the
    other providers' behaviour: the OTP request then answers the catalogued
    503 uniformly instead of pretending a code was delivered.
    """

    def __init__(self, client: BaleBotClient | None = None) -> None:
        # Fail closed on the deployment-resolution path (no injected client);
        # explicit clients (tests, tooling) carry their own configuration.
        if client is None and not bale_bot_token():
            raise AppError(_GENERIC_FAILURE)
        self._client = client if client is not None else BaleBotClient()

    async def send(self, phone: str, body: str, code: str | None = None) -> None:
        """Deliver one OTP message to the chat linked to ``phone``.

        A phone without a linked chat raises the generic error (the OTP
        service then burns the code); the response never reveals whether a
        phone is linked. Runs with its own DB session because delivery
        happens after the request session is closed.
        """
        from app.database import SessionLocal

        async with SessionLocal() as db:
            chat_id = await get_chat_id_for_phone(db, phone)
        if not chat_id:
            raise AppError(_GENERIC_FAILURE)
        try:
            await self._client.send_message(chat_id, body)
        except BaleApiError:
            raise AppError(_GENERIC_FAILURE) from None


_me_lock: asyncio.Lock | None = None
_bot_username_cache: str | None = None


def reset_runtime_state() -> None:
    """Test helper: forget the cached bot username and lock."""
    global _me_lock, _bot_username_cache
    _me_lock = None
    _bot_username_cache = None


async def get_bot_username(client: BaleBotClient | None = None) -> str | None:
    """Bot username for deep links (``ble.ir/<username>``), cached per process.

    Returns ``None`` when the token is missing or ``getMe`` fails; failures
    are not cached so a recovered token/network is picked up on the next
    call without a restart.
    """
    global _me_lock, _bot_username_cache
    if not bale_bot_token():
        return None
    if _bot_username_cache is not None:
        return _bot_username_cache
    if _me_lock is None:
        _me_lock = asyncio.Lock()
    async with _me_lock:
        if _bot_username_cache is not None:
            return _bot_username_cache
        try:
            me = await (client if client is not None else BaleBotClient()).get_me()
        except Exception:
            return None
        username = str(me.get("username") or "").lstrip("@").strip() or None
        if username is not None:
            _bot_username_cache = username
        return username


async def describe_otp_channel() -> dict[str, str | None]:
    """Public delivery-channel descriptor for the patient login screen.

    Only the provider name and the bot's public deep link are exposed —
    never any account or phone state.
    """
    from app.auth.sms import provider_name

    provider = provider_name()
    if provider != "bale":
        return {"provider": provider, "bot_username": None, "bot_url": None}
    username = await get_bot_username()
    return {
        "provider": provider,
        "bot_username": username,
        "bot_url": f"https://ble.ir/{username}" if username else None,
    }


async def run_bale_poller(
    client: BaleBotClient | None = None,
    stop: asyncio.Event | None = None,
) -> None:
    """Long-poll loop; one update at a time, forever, with backoff.

    On start, pending updates are drained with a short poll: fresh ones are
    processed (a contact share sent while the app was down still links) and
    stale ones are skipped while still advancing the offset.
    """
    bot = client if client is not None else BaleBotClient()
    offset: int | None = None
    backoff = _POLL_BACKOFF_START_SECONDS
    while stop is None or not stop.is_set():
        try:
            updates = await bot.get_updates(offset, timeout=bale_poll_timeout_seconds())
            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = update_id + 1
                age = _update_age_seconds(update)
                if age is not None and age > _MAX_BACKLOG_AGE_SECONDS:
                    continue
                await process_update(update, client=bot)
            backoff = _POLL_BACKOFF_START_SECONDS
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Bale poller cycle failed; retrying after backoff")
            if stop is not None:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=backoff)
                except TimeoutError:
                    pass
            else:
                await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _POLL_BACKOFF_MAX_SECONDS)


_poller_task: asyncio.Task[None] | None = None


def start_bale_poller() -> None:
    """Start the in-process poller when the Bale channel is fully configured."""
    global _poller_task
    from app.auth.sms import provider_name

    if provider_name() != "bale":
        return
    if not bale_bot_token():
        logger.warning("OTP_PROVIDER=bale without BALE_BOT_TOKEN: OTP login cannot deliver codes")
        return
    if not bale_poller_enabled():
        logger.info("Bale poller disabled by BALE_POLLER_ENABLED")
        return
    if _poller_task is not None and not _poller_task.done():
        return
    _poller_task = asyncio.get_running_loop().create_task(run_bale_poller(), name="bale-otp-poller")
    logger.info("Bale OTP poller started")


def stop_bale_poller() -> None:
    global _poller_task
    if _poller_task is not None and not _poller_task.done():
        _poller_task.cancel()
    _poller_task = None
