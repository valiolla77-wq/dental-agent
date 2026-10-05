from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pwdlib import PasswordHash

from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse


router = APIRouter(
    prefix="/users",
    tags=["Users"],
)

password_hash = PasswordHash.recommended()


@router.post("/", response_model=UserResponse)
async def create_user(
    user: UserCreate,
    db: AsyncSession = Depends(get_db),
):
    new_user = User(
        full_name=user.full_name,
        phone=user.phone,
        password_hash=password_hash.hash(user.password),
        role=user.role,
    )

    db.add(new_user)

    await db.commit()
    await db.refresh(new_user)

    return new_user