"""Seed a realistic service catalog and sample doctors for triage testing.

This script is ADDITIVE and idempotent, and works on the database the
application itself uses (DATABASE_URL, default ``dental_agent.db``). It never
touches users, patients, or appointments, and never rewrites existing rows:
existing services (same name), doctors (same phone) and schedules (same
doctor+day) are left exactly as they are.

Run:
    .\\.venv\\Scripts\\python.exe scripts\\seed_catalog.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.database import DATABASE_URL, SessionLocal, init_db  # noqa: E402
from app.models.dental_service import DentalService  # noqa: E402
from app.models.doctor import Doctor  # noqa: E402
from app.models.doctor_schedule import DoctorSchedule  # noqa: E402

# Realistic service catalog for a dental clinic (name, description).
SERVICES: list[tuple[str, str]] = [
    ("معاینه و مشاوره", "معاینه کامل دهان و دندان، طرح درمان و مشاوره."),
    ("جرم‌گیری و بروساژ", "پاک‌سازی جرم و پلاک برای پیشگیری از بیماری لثه."),
    ("ترمیم کامپوزیت", "ترمیم دندان با کامپوزیت هم‌رنگ دندان."),
    ("ترمیم آمالگام", "ترمیم استاندارد سطوح آسیب‌دیده با آمالگام."),
    ("درمان ریشه (عصب‌کشی)", "درمان کانال ریشه برای نگه‌داشتن دندان."),
    ("کشیدن دندان", "خارج‌کردن دندان ترمیم‌ناپذیر با بی‌حسی موضعی."),
    ("روکش سرامیکی (زرس)", "روکش بدون فلز با ظاهری طبیعی."),
    ("روکش PFM", "روکش فلز-سرامیک اقتصادی و مقاوم."),
    ("ایمپلنت دندانی", "کاشت فیکسچر تیتانیومی برای جایگزینی دندان از‌دست‌رفته."),
    ("ارتدنسی ثابت (براکت)", "اصلاح ردیف دندان با براکت و سیم."),
    ("ارتدنسی متحرک", "دستگاه اصلاحی متحرک برای کودکان و نوجوانان."),
    ("بلیچینگ دندان", "روشن‌کردن رنگ دندان‌ها با مواد مجاز."),
]

# Fake doctors with their specialty and the services they actually provide.
# (full name, specialty, phone, indexes into SERVICES above)
DOCTORS: list[tuple[str, str, str, list[int]]] = [
    (
        "دکتر سارا احمدی", "دندانپزشک عمومی", "09210100001",
        [0, 1, 2, 3, 5, 11],
    ),
    (
        "دکتر فرزاد نوری", "متخصص ترمیمی و زیبایی", "09210100002",
        [2, 6, 7, 11],
    ),
    (
        "دکتر محمد رضایی", "متخصص اندودانتیکس (درمان ریشه)", "09210100003",
        [0, 4, 5],
    ),
    (
        "دکتر مریم موسوی", "متخصص پروتز و ایمپلنت", "09210100004",
        [6, 7, 8],
    ),
    (
        "دکتر علی کریمی", "متخصص جراحی دهان، فک و صورت", "09210100005",
        [5, 8],
    ),
    (
        "دکتر نگار حسینی", "متخصص ارتدنسی", "09210100006",
        [9, 10],
    ),
]

# Weekly working plan (شنبه=0 … جمعه=6). Doctor index → list of shifts.
SCHEDULES: dict[int, list[tuple[int, str, str, int]]] = {
    0: [(0, "08:30", "16:00", 30), (1, "08:30", "16:00", 30),
        (2, "08:30", "16:00", 30), (3, "08:30", "13:00", 30)],
    1: [(0, "09:00", "15:30", 45), (2, "09:00", "15:30", 45),
        (4, "08:00", "12:00", 45)],
    2: [(0, "09:00", "14:00", 60), (1, "09:00", "14:00", 60),
        (3, "15:00", "19:00", 60)],
    3: [(0, "10:00", "18:00", 60), (2, "10:00", "18:00", 60),
        (4, "09:00", "13:00", 60)],
    4: [(1, "08:00", "13:00", 45), (3, "08:00", "13:00", 45)],
    5: [(0, "15:00", "19:00", 45), (2, "15:00", "19:00", 45),
        (4, "10:00", "14:00", 45)],
}


async def _existing_service(db, name: str) -> DentalService | None:
    result = await db.execute(select(DentalService).where(DentalService.name == name))
    return result.scalar_one_or_none()


async def _existing_doctor(db, phone: str) -> Doctor | None:
    result = await db.execute(select(Doctor).where(Doctor.phone == phone))
    return result.scalar_one_or_none()


async def seed() -> None:
    # Tables must exist even when this runs before the first server start.
    await init_db()

    created_services = created_doctors = created_schedules = created_links = 0

    async with SessionLocal() as db:
        services: list[DentalService] = []
        for name, description in SERVICES:
            service = await _existing_service(db, name)
            if service is None:
                service = DentalService(name=name, description=description, is_active=True)
                db.add(service)
                await db.flush()
                created_services += 1
            services.append(service)

        for index, (full_name, specialty, phone, service_indexes) in enumerate(DOCTORS):
            doctor = await _existing_doctor(db, phone)
            if doctor is None:
                doctor = Doctor(full_name=full_name, specialty=specialty, phone=phone)
                doctor.dental_services = [services[i] for i in service_indexes]
                db.add(doctor)
                await db.flush()
                created_doctors += 1
                created_links += len(service_indexes)

            for day, start, end, minutes in SCHEDULES.get(index, []):
                duplicate = await db.execute(
                    select(DoctorSchedule).where(
                        DoctorSchedule.doctor_id == doctor.id,
                        DoctorSchedule.day_of_week == day,
                    )
                )
                if duplicate.scalar_one_or_none() is not None:
                    continue
                db.add(
                    DoctorSchedule(
                        doctor_id=doctor.id,
                        day_of_week=day,
                        start_time=time.fromisoformat(start),
                        end_time=time.fromisoformat(end),
                        slot_duration_minutes=minutes,
                        is_active=True,
                    )
                )
                created_schedules += 1

        await db.commit()

    total_services = len(SERVICES)
    total_doctors = len(DOCTORS)
    print(f"created services : {created_services} (catalog total: {total_services})")
    print(f"created doctors  : {created_doctors} (catalog total: {total_doctors})")
    print(f"created schedules: {created_schedules}")
    print(f"created links    : {created_links}")
    print(f"database: {DATABASE_URL}")


if __name__ == "__main__":
    asyncio.run(seed())
