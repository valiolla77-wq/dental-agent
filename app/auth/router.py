"""Authentication router."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import otp as otp_service
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
    db: AsyncSession = Depends(get_db),
):
    """Authenticate user and return access token."""
    # Find user by phone
    result = await db.execute(select(User).where(User.phone == login_data.phone))
    user = result.scalar_one_or_none()

    # Generic error for both user not found and wrong password
    if user is None or not verify_password(login_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid phone or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User is inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create access token with user ID as subject
    access_token = create_access_token(subject=str(user.id))

    return TokenResponse(access_token=access_token)


def _client_ip(request: Request) -> str:
    if request.client is not None:
        return request.client.host
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
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