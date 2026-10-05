from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.clinic_setting import ClinicSetting
from app.schemas.clinic_setting import (
    ClinicSettingResponse,
    ClinicSettingUpdate,
)


router = APIRouter(
    prefix="/clinic-settings",
    tags=["Clinic Settings"],
)


@router.get(
    "/",
    response_model=ClinicSettingResponse,
)
async def get_clinic_settings(
    db: AsyncSession = Depends(get_db),
):
    settings = await db.get(
        ClinicSetting,
        1,
    )

    if settings is None:
        settings = ClinicSetting(
            id=1,
            max_appointments_per_day=0,
            max_appointments_per_week=0,
            max_appointments_per_month=0,
        )

        db.add(settings)

        await db.commit()
        await db.refresh(settings)

    return settings


@router.put(
    "/",
    response_model=ClinicSettingResponse,
)
async def update_clinic_settings(
    settings_data: ClinicSettingUpdate,
    db: AsyncSession = Depends(get_db),
):
    settings = await db.get(
        ClinicSetting,
        1,
    )

    if settings is None:
        settings = ClinicSetting(
            id=1,
        )

        db.add(settings)

    settings.max_appointments_per_day = (
        settings_data.max_appointments_per_day
    )

    settings.max_appointments_per_week = (
        settings_data.max_appointments_per_week
    )

    settings.max_appointments_per_month = (
        settings_data.max_appointments_per_month
    )

    await db.commit()
    await db.refresh(settings)

    return settings