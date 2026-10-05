from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.doctor import Doctor
from app.schemas.doctor import (
    DoctorCreate,
    DoctorResponse,
    DoctorUpdate,
)


router = APIRouter(
    prefix="/doctors",
    tags=["Doctors"],
)


@router.post("/", response_model=DoctorResponse)
async def create_doctor(
    doctor: DoctorCreate,
    db: AsyncSession = Depends(get_db),
):
    new_doctor = Doctor(
        full_name=doctor.full_name,
        specialty=doctor.specialty,
        phone=doctor.phone,
    )

    db.add(new_doctor)

    await db.commit()
    await db.refresh(new_doctor)

    return new_doctor