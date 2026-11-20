"""Authentication router."""

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import bale as bale_otp
from app.auth import otp as otp_service
from app.auth.dependencies import get_current_user
from app.auth.permissions import linked_doctor_id, linked_patient_ids
from app.auth.rate_limit import login_rate_limiter
from app.auth.schemas import (
    LoginRequest,
    MeLinkInfo,
    MeResponse,
    OtpChannelResponse,
    OtpRequest,
    OtpRequestResponse,
    OtpVerifyRequest,
    TokenResponse,
)
from app.auth.security import create_access_token, verify_password_async
from app.database import get_db
from app.errors import AppError
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.user import User

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)

# Verified against for unknown phone numbers so a failed login takes roughly
# the same time whether or not the account exists. This hash is for a random
# throwaway password and is never accepted for any real account.
_DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$OgaW8JF26SLaA+DXWYCrVg$"
    "LmvJ10c00jGPz9WVqZuXjOW62RXFO0ZmecK4N8pfLQI"
)

# The two web portals: patients never sign in through the staff door and
# staff never sign in through the patient door. ``None`` keeps the legacy
# behaviour (any active account) for API compatibility.
_PORTAL_ROLES: dict[str, frozenset[str]] = {
    "patient": frozenset({"patient"}),
    "staff": frozenset({"admin", "receptionist", "doctor"}),
}


async def _authenticate_password_login(
    db: AsyncSession,
    login_data: LoginRequest,
    ip: str,
) -> User:
    """Shared password login core with rate limiting and portal gating.

    The rate limiter runs before any credential check, one Argon2
    verification always runs (uniform timing for unknown phones), and the
    portal check happens only after the password is proven correct so the
    response never reveals more than the caller already knows.
    """
    phone = login_data.phone
    login_rate_limiter.check(ip=ip, phone=phone)

    # Find user by phone
    result = await db.execute(select(User).where(User.phone == phone))
    user = result.scalar_one_or_none()

    # Always run one Argon2 verification, including for unknown accounts, so
    # response timing does not reveal whether a phone is registered.
    password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_ok = await verify_password_async(login_data.password, password_hash)

    # One generic response for unknown users, wrong passwords, and inactive
    # accounts; none of those states may be distinguished by the caller.
    if user is None or not password_ok or not user.is_active:
        login_rate_limiter.record_failure(ip=ip, phone=phone)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid phone or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    login_rate_limiter.record_success(phone=phone)

    # Separate doors: a staff account cannot use the patient portal and a
    # patient account cannot use the staff portal. The check runs after the
    # password verdict so timing/behaviour stays uniform until then.
    if login_data.portal is not None:
        allowed = _PORTAL_ROLES.get(login_data.portal, frozenset())
        if user.role not in allowed:
            raise AppError("AUTH_PORTAL_MISMATCH")

    # Bookkeeping: remember the last successful sign-in for the staff panel.
    user.last_login_at = datetime.now(UTC).replace(tzinfo=None)
    await db.commit()
    return user


@router.post("/login", response_model=TokenResponse)
async def login(
    login_data: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate user and return access token.

    Failed attempts are rate limited per target phone and per client IP
    (see app/auth/rate_limit.py). When the request declares a ``portal``,
    only accounts of that portal's roles are accepted.
    """
    user = await _authenticate_password_login(
        db, login_data, _client_ip(request)
    )

    # Create access token; the password-hash digest binds the token to the
    # current credential so a later reset revokes outstanding tokens.
    access_token = create_access_token(
        subject=str(user.id), password_hash=user.password_hash
    )

    return TokenResponse(access_token=access_token)


@router.post("/staff/login", response_model=TokenResponse)
async def staff_login(
    login_data: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Staff-only door: password login for admin/receptionist/doctor accounts.

    Patient-role accounts are rejected with a catalogued error even when the
    password is correct, so the clinic back-office and the patient app are
    enforcedly separate entry points.
    """
    user = await _authenticate_password_login(
        db,
        LoginRequest(
            phone=login_data.phone, password=login_data.password, portal="staff"
        ),
        _client_ip(request),
    )
    access_token = create_access_token(
        subject=str(user.id), password_hash=user.password_hash
    )
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
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Issue a one-time code; the response is uniform for every phone.

    Delivery is scheduled after the response is dispatched, so vendor I/O
    never changes the response latency or status of any phone (see
    ``otp.request_otp``): staff accounts cannot be classified by timing and
    a vendor failure cannot turn one phone's answer into a 503 while another
    stays 202.
    """
    result = await otp_service.request_otp(
        db, payload.phone, _client_ip(request), background=background_tasks
    )
    return OtpRequestResponse(**result)


@router.get("/otp/channel", response_model=OtpChannelResponse)
async def otp_delivery_channel():
    """Which channel delivers the patient OTP code, for the login screen.

    Public and stateless: the answer depends only on deployment
    configuration, never on the caller or any phone number, so it cannot
    leak account state. For the Bale channel it includes the bot's public
    ``ble.ir`` deep link when the bot identity is reachable.
    """
    return OtpChannelResponse(**await bale_otp.describe_otp_channel())


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


@router.get("/me", response_model=MeResponse)
async def me(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Profile of the authenticated account plus every linked patient record.

    The records are always the caller's own; the lookup is server-side by
    user id so no client-supplied id can widen it. ``patient`` remains the
    primary (account-holder) record for backwards compatibility.
    """
    response = MeResponse(
        full_name=current_user.full_name,
        phone=current_user.phone,
        role=current_user.role,
        is_active=current_user.is_active,
    )
    if current_user.role == "patient":
        linked_ids = await linked_patient_ids(db, current_user)
        patients = []
        for linked_id in linked_ids:
            patient = await db.get(Patient, linked_id)
            if patient is not None:
                patients.append(patient)
        response.patients = [
            MeLinkInfo(
                id=patient.id,
                full_name=patient.full_name,
                is_account_holder=patient.is_account_holder,
            )
            for patient in patients
        ]
        if response.patients:
            response.patient = response.patients[0]
    elif current_user.role == "doctor":
        linked_id = await linked_doctor_id(db, current_user)
        if linked_id is not None:
            doctor = await db.get(Doctor, linked_id)
            if doctor is not None:
                response.doctor = MeLinkInfo(
                    id=doctor.id, full_name=doctor.full_name
                )
    return response