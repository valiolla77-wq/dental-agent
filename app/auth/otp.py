"""Patient phone OTP issuance and verification with conservative limits.

Design notes:
- Only HMAC-SHA256 hashes are persisted; plaintext codes never touch the DB.
- Codes are single-use and expire (default 5 minutes). A wrong code counts
  an attempt (default 5 max). Issuing a new code invalidates previous ones.
- Resend cooldown (default 60 seconds) and per-phone/per-IP rate limits keep
  OTP brute forcing impractical; OTPs are never logged.
- Responses never reveal whether the phone belongs to an account, and an OTP
  never links or authenticates a staff account. Attempt counting and
  cooldown consumption use atomic conditional UPDATEs so concurrent requests
  cannot lose an increment or double-trigger delivery.
- Delivery happens after the response is dispatched (when the HTTP layer
  provides a scheduler): vendor I/O cost is identical for every phone, so
  response latency cannot classify staff accounts, and a vendor failure can
  no longer differ between response codes. Misconfiguration still fails
  closed synchronously with the catalogued 503.
- Datetimes use the naive-UTC convention already used for appointment times.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import (
    _get_jwt_secret,
    create_access_token,
    hash_password_async,
)
from app.auth.sms import fake_provider_allowed, get_sms_provider
from app.errors import AppError
from app.models.otp import OtpCode
from app.models.user import User

logger = logging.getLogger(__name__)


class DeliveryScheduler(Protocol):
    """Minimal shape of FastAPI's BackgroundTasks (for decoupled typing)."""

    def add_task(self, func: Any, /, *args: Any, **kwargs: Any) -> None: ...


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _expiry_minutes() -> int:
    try:
        return max(1, int(os.getenv("OTP_EXPIRY_MINUTES", "5")))
    except ValueError:
        return 5


def _max_attempts() -> int:
    try:
        return max(1, int(os.getenv("OTP_MAX_ATTEMPTS", "5")))
    except ValueError:
        return 5


def _resend_cooldown_seconds() -> int:
    try:
        return max(0, int(os.getenv("OTP_RESEND_COOLDOWN_SECONDS", "60")))
    except ValueError:
        return 60


def _ip_rate_limit() -> tuple[int, int]:
    try:
        limit = max(1, int(os.getenv("OTP_IP_REQUEST_LIMIT", "10")))
    except ValueError:
        limit = 10
    try:
        window = max(30, int(os.getenv("OTP_IP_REQUEST_WINDOW_SECONDS", "300")))
    except ValueError:
        window = 300
    return limit, window


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


_ip_requests: dict[str, list[float]] = {}
_MAX_TRACKED_KEYS = 10_000


def _prune_stale(table: dict[str, list[float]], moment: float, window: float) -> None:
    """Bound memory: drop keys whose newest hit already left the window."""
    if len(table) <= _MAX_TRACKED_KEYS:
        return
    for key in [k for k, marks in table.items() if not marks or moment - marks[-1] >= window]:
        del table[key]


def _check_ip_rate_limit(ip: str) -> None:
    limit, window = _ip_rate_limit()
    moment = time.monotonic()
    history = [mark for mark in _ip_requests.get(ip, []) if moment - mark < window]
    history.append(moment)
    _ip_requests[ip] = history
    _prune_stale(_ip_requests, moment, window)
    if len(history) > limit:
        raise AppError("COMMON_TOO_MANY_REQUESTS")


class _SmsAbuseGuard:
    """Caps on OTP *issuance* so SMS credit cannot be drained.

    Independent of the per-IP limiter (which a botnet sidesteps): one phone may
    receive only a few codes per day and the whole service only so many per
    hour. Counters are in memory and per process.
    """

    _DAY = 86_400.0
    _HOUR = 3_600.0

    def __init__(self) -> None:
        self._per_phone: dict[str, list[float]] = {}
        self._global: list[float] = []

    def check_and_record(self, phone: str) -> None:
        moment = time.monotonic()
        phone_limit = _env_int("OTP_PHONE_DAILY_LIMIT", 10)
        global_limit = _env_int("OTP_GLOBAL_HOURLY_LIMIT", 300)

        phone_hits = [m for m in self._per_phone.get(phone, []) if moment - m < self._DAY]
        self._global = [m for m in self._global if moment - m < self._HOUR]
        if len(phone_hits) >= phone_limit or len(self._global) >= global_limit:
            self._per_phone[phone] = phone_hits
            raise AppError("COMMON_TOO_MANY_REQUESTS")

        phone_hits.append(moment)
        self._per_phone[phone] = phone_hits
        self._global.append(moment)
        _prune_stale(self._per_phone, moment, self._DAY)

    def reset(self) -> None:
        self._per_phone.clear()
        self._global.clear()


sms_abuse_guard = _SmsAbuseGuard()


def _otp_key() -> bytes:
    """Domain-separated key so OTP hashes never reuse the raw JWT secret."""
    return hashlib.sha256(
        b"dental-agent:otp-code:v1:" + _get_jwt_secret().encode("utf-8")
    ).digest()


def _code_hash(phone: str, code: str) -> str:
    return hmac.new(
        _otp_key(),
        f"{phone}:{code}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _new_code() -> str:
    return f"{secrets.randbelow(1000000):06d}"


async def _latest_code(db: AsyncSession, phone: str) -> OtpCode | None:
    result = await db.execute(
        select(OtpCode)
        .where(OtpCode.phone == phone, OtpCode.consumed_at.is_(None))
        .order_by(OtpCode.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()

async def _deliver_otp(
    provider: Any,
    phone: str,
    body: str,
    code: str,
    otp_record_id: int,
) -> None:
    """Post-response delivery with burn-on-failure, using its own session.

    The request-scoped session is closed by the time background tasks run,
    so the invalidation opens a fresh one. A vendor failure is logged
    without any vendor detail; the code is burned so the resend cooldown
    cannot lock the patient out of retrying once the vendor recovers.
    """
    from app.database import SessionLocal

    try:
        await provider.send(phone, body, code=code)
    except Exception:
        logger.warning("OTP delivery failed; the code was invalidated")
        try:
            async with SessionLocal() as session:
                await session.execute(
                    update(OtpCode)
                    .where(
                        OtpCode.id == otp_record_id,
                        OtpCode.consumed_at.is_(None),
                    )
                    .values(consumed_at=_utcnow())
                )
                await session.commit()
        except Exception:
            logger.error("OTP burn after failed delivery did not complete")


async def request_otp(
    db: AsyncSession,
    phone: str,
    ip: str,
    background: DeliveryScheduler | None = None,
) -> dict[str, str | None]:
    """Issue a code for a phone. Uniform response; never leaks account state.

    ``background`` is provided by the HTTP layer: delivery is then scheduled
    after the response and any vendor failure only invalidates the code.
    Without it (direct service calls), delivery stays synchronous and a
    vendor failure keeps the catalogued 503 behaviour.
    """
    normalized = (phone or "").strip()
    _check_ip_rate_limit(ip or "unknown")

    now = _utcnow()
    previous = await _latest_code(db, normalized)
    if previous is not None:
        elapsed = (now - previous.created_at).total_seconds()
        if elapsed < _resend_cooldown_seconds():
            raise AppError("COMMON_TOO_MANY_REQUESTS")
        # Atomically claim the previous code. Two concurrent requests can
        # both pass the cooldown check, but only one UPDATE matches the
        # ``consumed_at IS NULL`` guard, so only one of them proceeds to
        # trigger delivery.
        claimed = await db.execute(
            update(OtpCode)
            .where(OtpCode.id == previous.id, OtpCode.consumed_at.is_(None))
            .values(consumed_at=now)
        )
        if claimed.rowcount == 0:
            raise AppError("COMMON_TOO_MANY_REQUESTS")
        await db.flush()

    sms_abuse_guard.check_and_record(normalized)

    code = _new_code()
    record = OtpCode(
        phone=normalized,
        code_hash=_code_hash(normalized, code),
        attempts=0,
        expires_at=now + timedelta(minutes=_expiry_minutes()),
        created_at=now,
        consumed_at=None,
    )
    db.add(record)
    await db.commit()

    user = (
        await db.execute(select(User).where(User.phone == normalized))
    ).scalar_one_or_none()
    eligible = user is None or user.role == "patient"

    # Provider construction is validated synchronously for every phone and
    # fails closed: a misconfigured deployment answers the catalogued 503
    # uniformly instead of leaking account state through differing status
    # codes. The (possibly expensive) vendor call itself never happens
    # before the response when a scheduler is available.
    provider = get_sms_provider()

    if eligible:
        body = f"کد ورود شما: {code}"
        if background is not None:
            background.add_task(
                _deliver_otp, provider, normalized, body, code, record.id
            )
        else:
            try:
                await provider.send(normalized, body, code=code)
            except Exception:
                # Delivery failed (vendor, configuration, or network). Burn
                # the stored code so the resend cooldown cannot lock the
                # user out, and expose only the generic service error; never
                # the vendor detail.
                record.consumed_at = _utcnow()
                await db.commit()
                raise AppError("COMMON_SERVICE_UNAVAILABLE") from None

    # Dev-only exposure: the fake provider is the only channel, and both the
    # env gate and the explicit note mark it unsafe outside dev/test.
    response: dict[str, str | None] = {
        "status": "accepted",
        "message": "اگر این شماره متعلق به بیمار باشد، کد ورود ارسال می‌شود.",
        "dev_otp": None,
        "dev_notice": None,
    }
    if fake_provider_allowed() and eligible:
        response["dev_otp"] = code
        response["dev_notice"] = (
            "DEVELOPMENT ONLY fake SMS provider; never enable outside dev/test."
        )
    return response


async def _unauthorized() -> None:
    raise AppError("COMMON_UNAUTHORIZED")


async def verify_otp(db: AsyncSession, phone: str, code: str, ip: str) -> str:
    """Verify a code and return a JWT for the patient's own account.

    A matching code never authenticates a staff account and never links an
    existing patient record; linkage is explicit staff work elsewhere.
    """
    normalized = (phone or "").strip()
    candidate = (code or "").strip()
    _check_ip_rate_limit(ip or "unknown")

    now = _utcnow()
    record = await _latest_code(db, normalized)
    if record is None:
        await _unauthorized()
    assert record is not None
    if now >= record.expires_at:
        record.consumed_at = now
        await db.commit()
        await _unauthorized()
    if record.attempts >= _max_attempts():
        await _unauthorized()
    if not hmac.compare_digest(record.code_hash, _code_hash(normalized, candidate)):
        # Atomic conditional UPDATE instead of a read-modify-write: two
        # concurrent wrong submissions must each count, otherwise one
        # increment is lost and the effective number of guesses exceeds the
        # configured maximum.
        await db.execute(
            update(OtpCode)
            .where(OtpCode.id == record.id)
            .values(attempts=OtpCode.attempts + 1)
        )
        await db.commit()
        await _unauthorized()

    record.consumed_at = now
    await db.flush()

    user = (
        await db.execute(select(User).where(User.phone == normalized))
    ).scalar_one_or_none()
    if user is None:
        user = User(
            full_name="بیمار",
            phone=normalized,
            password_hash=await hash_password_async(secrets.token_urlsafe(32)),
            role="patient",
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    elif user.role != "patient" or not user.is_active:
        await db.commit()
        await _unauthorized()

    await db.commit()
    return create_access_token(
        subject=str(user.id), password_hash=user.password_hash
    )


async def purge_phone_codes(db: AsyncSession, phone: str) -> None:
    """Test helper: remove all OTP rows for one phone."""
    await db.execute(delete(OtpCode).where(OtpCode.phone == phone))
    await db.commit()
