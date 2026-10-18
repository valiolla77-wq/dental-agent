"""Authentication router."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import otp as otp_service
from app.auth.rate_limit import login_rate_limiter
from app.auth.schemas import (
    LoginRequest,
    OtpRequest,
    OtpRequestResponse,
    OtpVerifyRequest,
    TokenResponse,
)
from app.auth.security import create_access_token, hash_password, verify_password
from app.database import get_db
from app.models.user import User

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


@router.post("/login", response_model=TokenResponse)
async def login(
    login_data: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate user and return access token.

    Failed attempts are rate limited per target phone and per client IP
    (see app/auth/rate_limit.py). The limiter runs before any credential
    check so existing, unknown, and inactive phones are throttled exactly
    the same way.
    """
    ip = _client_ip(request)
    phone = login_data.phone
    login_rate_limiter.check(ip=ip, phone=phone)

    # Find user by phone
    result = await db.execute(select(User).where(User.phone == phone))
    user = result.scalar_one_or_none()

    # Generic error for both user not found and wrong password
    if user is None or not verify_password(login_data.password, user.password_hash):
        login_rate_limiter.record_failure(ip=ip, phone=phone)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid phone or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        # Counted as a failure so a correct password on an inactive account
        # cannot be distinguished from a wrong password by throttling.
        login_rate_limiter.record_failure(ip=ip, phone=phone)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User is inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    login_rate_limiter.record_success(phone=phone)

    # Create access token with user ID as subject
    access_token = create_access_token(subject=str(user.id))

    return TokenResponse(access_token=access_token)


def _client_ip(request: Request) -> str:
    """Best-effort client IP for rate limiting.

    Only ``request.client.host`` is trusted. The client-supplied
    ``X-Forwarded-For`` header is deliberately ignored so a forged header
    can never change the limiter's IP key; enabling proxy-aware IP
    extraction requires explicit trusted-proxy configuration (not done
    here). When the transport provides no client info, a stable neutral
    placeholder is used instead of falling back to request headers.
    """
    client = request.client
    if client is not None and client.host:
        return client.host
    return "unknown"


@router.post(
    "/otp/request",
    response_model=OtpRequestResponse,
    status_code=202,
)
async def request_otp_code(
    payload: OtpRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Issue a one-time code; the response is uniform for every phone."""
    result = await otp_service.request_otp(db, payload.phone, _client_ip(request))
    return OtpRequestResponse(**result)


@router.post("/otp/verify", response_model=TokenResponse)
async def verify_otp_code(
    payload: OtpVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Verify a code and return a patient access token for a verified phone."""
    access_token = await otp_service.verify_otp(
        db, payload.phone, payload.code, _client_ip(request)
    )
    return TokenResponse(access_token=access_token)