"""Patient phone OTP issuance and verification with conservative limits.

Design notes:
- Only HMAC-SHA256 hashes are persisted; plaintext codes never touch the DB.
- Codes are single-use and expire (default 5 minutes). A wrong code counts
  an attempt (default 5 max). Issuing a new code invalidates previous ones.
- Resend cooldown (default 60 seconds) and per-phone/per-IP rate limits keep
  OTP brute forcing impractical; OTPs are never logged.
- Responses never reveal whether the phone belongs to an account, and an OTP
  never links or authenticates a staff account.
- Datetimes use the naive-UTC convention already used for appointment times.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import _get_jwt_secret, create_access_token, hash_password
from app.auth.sms import fake_provider_allowed, get_sms_provider
from app.errors import AppError
from app.models.otp import OtpCode
from app.models.user import User


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


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


_ip_requests: dict[str, list[float]] = {}


def _check_ip_rate_limit(ip: str) -> None:
    limit, window = _ip_rate_limit()
    moment = time.monotonic()
    history = [mark for mark in _ip_requests.get(ip, []) if moment - mark < window]
    history.append(moment)
    _ip_requests[ip] = history
    if len(history) > limit:
        raise AppError("COMMON_TOO_MANY_REQUESTS")


def _code_hash(phone: str, code: str) -> str:
    return hmac.new(
        _get_jwt_secret().encode("utf-8"),
        f"{phone}:{code}".encode("utf-8"),
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

async def request_otp(db: AsyncSession, phone: str, ip: str) -> dict[str, str | None]:
    """Issue a code for a phone. Uniform response; never leaks account state."""
    normalized = (phone or "").strip()
    _check_ip_rate_limit(ip or "unknown")

    now = _utcnow()
    previous = await _latest_code(db, normalized)
    if previous is not None:
        elapsed = (now - previous.created_at).total_seconds()
        if elapsed < _resend_cooldown_seconds():
            raise AppError("COMMON_TOO_MANY_REQUESTS")
        previous.consumed_at = now
        await db.flush()

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
    provider = get_sms_provider()
    if eligible:
        provider.send(normalized, f"کد ورود شما: {code}")

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
    if now > record.expires_at:
        record.consumed_at = now
        await db.commit()
        await _unauthorized()
    if record.attempts >= _max_attempts():
        await _unauthorized()
    if not hmac.compare_digest(record.code_hash, _code_hash(normalized, candidate)):
        record.attempts += 1
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
            password_hash=hash_password(secrets.token_urlsafe(32)),
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
    return create_access_token(subject=str(user.id))


async def purge_phone_codes(db: AsyncSession, phone: str) -> None:
    """Test helper: remove all OTP rows for one phone."""
    await db.execute(delete(OtpCode).where(OtpCode.phone == phone))
    await db.commit()
