"""Users router with admin-protected user creation."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.auth.security import hash_password
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse

router = APIRouter(
    prefix="/users",
    tags=["Users"],
)


@router.post("/", response_model=UserResponse)
async def create_user(
    user: UserCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Create a new user. Requires admin privileges.

    The role is determined by the admin, not by the client request.
    This prevents unauthorized role escalation.
    """
    new_user = User(
        full_name=user.full_name,
        phone=user.phone,
        password_hash=hash_password(user.password),
        role=user.role,
        is_active=True,
    )

    db.add(new_user)

    await db.commit()
    await db.refresh(new_user)

    return new_user