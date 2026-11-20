"""User management: admin-protected creation, listing, and maintenance.

Covers the staff back-office: account CRUD, role promotion/demotion with
self-lockout and last-admin guards, per-account permission overrides, and an
append-only audit trail for every sensitive change.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_admin
from app.auth.permissions import effective_permissions
from app.auth.security import hash_password_async
from app.database import get_db
from app.errors import AppError
from app.models.agent_confirmation import AgentConfirmation
from app.models.chat import AgentConversation, AgentMessage
from app.models.doctor import Doctor
from app.models.feedback import FeedbackReport
from app.models.patient import Patient
from app.models.user import User
from app.schemas.user import (
    UserCreate,
    UserPermissionsResponse,
    UserPermissionsUpdate,
    UserResponse,
    UserUpdate,
)
from app.services.audit_service import record_audit

router = APIRouter(
    prefix="/users",
    tags=["Users"],
)


async def _load_user(db: AsyncSession, user_id: int) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise AppError("COMMON_NOT_FOUND")
    return user


async def _count_other_active_admins(
    db: AsyncSession, exclude_user_id: int
) -> int:
    """Active admin accounts other than the excluded one."""
    result = await db.execute(
        select(func.count())
        .select_from(User)
        .where(
            User.role == "admin",
            User.is_active.is_(True),
            User.id != exclude_user_id,
        )
    )
    return int(result.scalar_one())


@router.post("/", response_model=UserResponse)
async def create_user(
    user: UserCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Create a new user. Requires admin privileges.

    The role is determined by the admin, not by the client request.
    This prevents unauthorized role escalation.
    """
    new_user = User(
        full_name=user.full_name,
        phone=user.phone,
        password_hash=await hash_password_async(user.password),
        role=user.role,
        is_active=True,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )

    db.add(new_user)
    try:
        await db.commit()
    except IntegrityError:
        # The unique index on users.phone is the final authority under
        # concurrent admin requests. No partial row is left behind.
        await db.rollback()
        raise AppError("COMMON_CONFLICT") from None
    await db.refresh(new_user)

    await record_audit(
        db,
        actor=admin,
        action="user.create",
        target_user_id=int(new_user.id),
        target_label=f"{new_user.full_name} ({new_user.phone})",
        detail={"role": new_user.role},
    )
    await db.commit()

    return new_user


@router.get("/", response_model=list[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """List all accounts. Admin only; password hashes are never serialized."""
    result = await db.execute(select(User).order_by(User.id))
    return [UserResponse.model_validate(user) for user in result.scalars().all()]


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """One account by id. Admin only; hashes never leave the server."""
    user = await _load_user(db, user_id)
    return UserResponse.model_validate(user)


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Permanently remove an account. Admin only, with strong guards.

    Self-deletion and deletion of the last active admin are rejected. Before
    the row is removed, its soft references (linked patient/doctor records,
    feedback) are detached, and its private agent data (chat conversations
    with their messages, pending write confirmations) is deleted, because
    those rows are owned exclusively by the account and their ``user_id``
    columns are NOT NULL. No orphaned foreign keys remain. The removal is
    written to the audit trail.
    """
    user = await _load_user(db, user_id)
    if user.id == admin.id:
        raise AppError("COMMON_CONFLICT")
    if user.role == "admin" and user.is_active:
        if await _count_other_active_admins(db, user.id) == 0:
            raise AppError("USER_LAST_ADMIN_PROTECTED")

    target_label = f"{user.full_name} ({user.phone})"
    detail = {"role": user.role, "phone": user.phone}

    # Detach soft references; these tables keep their rows but no longer
    # point at the removed account.
    await db.execute(
        Patient.__table__.update()
        .where(Patient.user_id == user.id)
        .values(user_id=None, is_account_holder=False)
    )
    await db.execute(
        Doctor.__table__.update().where(Doctor.user_id == user.id).values(user_id=None)
    )
    # Delete the account's private agent data. Conversations and pending
    # confirmations exist only for their owner (every query scopes them by
    # user_id and their user_id columns are NOT NULL), so detaching them
    # would leave unreachable rows; removing them outright is both safe and
    # the only constraint-honouring option.
    user_conversations = select(AgentConversation.id).where(
        AgentConversation.user_id == user.id
    )
    await db.execute(
        delete(AgentMessage).where(
            AgentMessage.conversation_id.in_(user_conversations)
        )
    )
    await db.execute(
        delete(AgentConversation).where(
            AgentConversation.user_id == user.id
        )
    )
    await db.execute(
        delete(AgentConfirmation).where(
            AgentConfirmation.user_id == user.id
        )
    )
    await db.execute(
        FeedbackReport.__table__.update()
        .where(FeedbackReport.user_id == user.id)
        .values(user_id=None)
    )

    await record_audit(
        db,
        actor=admin,
        action="user.delete",
        target_user_id=int(user.id),
        target_label=target_label,
        detail=detail,
    )
    await db.delete(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise AppError("COMMON_CONFLICT") from None
    return {"message": "حساب کاربری حذف شد.", "user_id": user_id}


class ProfileSelfUpdate(BaseModel):
    """Self-service profile edit; deliberately narrow for safety.

    Only the display name is changeable. The phone number is the login
    identity (OTP) and patient records bind to it uniquely, so changing it
    stays a reception/admin desk operation. Role and account state are admin
    duties handled by ``PUT /users/{user_id}``.
    """

    full_name: str = Field(min_length=3, max_length=150)


@router.put("/me", response_model=UserResponse)
async def update_my_profile(
    payload: ProfileSelfUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Let any active account rename itself; phone/role stay protected.

    The display name is the only self-editable identity field: it appears in
    appointments and chat greetings but carries no authorization weight.
    Everything else (phone, role, active flag, permissions) requires the
    admin endpoints, and the change is written to the audit trail like any
    other account modification.
    """
    if not current_user.is_active:
        raise AppError("COMMON_FORBIDDEN")

    clean_name = payload.full_name.strip()
    if len(clean_name) < 3:
        raise AppError("COMMON_VALIDATION_ERROR")

    old_name = current_user.full_name
    current_user.full_name = clean_name

    await record_audit(
        db,
        actor=current_user,
        action="user.self_update",
        target_user_id=int(current_user.id),
        target_label=f"{clean_name} ({current_user.phone})",
        detail={"full_name": {"from": old_name, "to": clean_name}},
    )
    await db.commit()
    await db.refresh(current_user)
    return UserResponse.model_validate(current_user)


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
):
    """Update account state. Admin only; self-lockout is rejected.

    An admin may rename accounts, assign another role, enable/disable an
    account, or reset a password. Disabling or demoting the acting admin's
    own account is rejected so a single surviving admin cannot lock
    themselves out of the system. Deactivating or demoting the last active
    admin is also rejected. Role changes reset the account's permission
    overrides so pinned grants never silently survive a promotion/demotion.
    """
    user = await _load_user(db, user_id)
    if user.id == current_admin.id:
        if payload.is_active is False:
            raise AppError("COMMON_CONFLICT")
        if payload.role is not None and payload.role != user.role:
            raise AppError("COMMON_CONFLICT")
    if (
        user.role == "admin"
        and user.is_active
        and (
            payload.is_active is False
            or (payload.role is not None and payload.role != "admin")
        )
        and await _count_other_active_admins(db, user.id) == 0
    ):
        raise AppError("USER_LAST_ADMIN_PROTECTED")

    changes: dict[str, object] = {}
    if payload.full_name is not None and payload.full_name != user.full_name:
        changes["full_name"] = payload.full_name
        user.full_name = payload.full_name
    if payload.role is not None and payload.role != user.role:
        changes["role"] = {"from": user.role, "to": payload.role}
        user.role = payload.role
        # Pinned grants belong to the old role; never carry them over.
        user.permission_overrides = None
    if payload.is_active is not None and payload.is_active != user.is_active:
        changes["is_active"] = payload.is_active
        user.is_active = payload.is_active
    if payload.password is not None:
        changes["password"] = "reset"
        user.password_hash = await hash_password_async(payload.password)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise AppError("COMMON_CONFLICT") from None
    await db.refresh(user)

    if changes:
        await record_audit(
            db,
            actor=current_admin,
            action="user.update",
            target_user_id=int(user.id),
            target_label=f"{user.full_name} ({user.phone})",
            detail=changes,
        )
        await db.commit()
    return UserResponse.model_validate(user)


@router.get("/{user_id}/permissions", response_model=UserPermissionsResponse)
async def get_user_permissions(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Effective permission matrix of one account. Admin only."""
    user = await _load_user(db, user_id)
    actions = effective_permissions(user)
    return UserPermissionsResponse(
        user_id=int(user.id),
        role=user.role,
        actions=actions,  # type: ignore[arg-type]
    )


@router.put("/{user_id}/permissions", response_model=UserPermissionsResponse)
async def update_user_permissions(
    user_id: int,
    payload: UserPermissionsUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Replace the account's permission overrides. Admin only.

    Only receptionist/doctor accounts accept overrides: admins always keep
    full reach (the clinic can never be locked out) and patients are governed
    by ownership rules instead. An empty object clears all overrides.
    """
    user = await _load_user(db, user_id)
    if user.role not in ("receptionist", "doctor"):
        raise AppError("USER_PERMISSIONS_NOT_EDITABLE")

    old = user.overrides_dict()
    user.permission_overrides = dict(payload.overrides) or None

    await record_audit(
        db,
        actor=admin,
        action="user.permissions.update",
        target_user_id=int(user.id),
        target_label=f"{user.full_name} ({user.phone})",
        detail={"old": old, "new": payload.overrides},
    )
    await db.commit()
    await db.refresh(user)

    return UserPermissionsResponse(
        user_id=int(user.id),
        role=user.role,
        actions=effective_permissions(user),  # type: ignore[arg-type]
    )
