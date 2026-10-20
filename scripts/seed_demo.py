"""Idempotent demo data for the browser chat demo.

Safety contract:
- Requires an explicit ``DATABASE_URL`` that resolves exactly to the project's
  ``demo.db``. Any other path (including the real ``dental_agent.db``) is
  rejected before any database connection is opened.
- Only creates missing rows; it never deletes, truncates, or resets a database.
- Demo credentials are intentionally non-production sample values.

Run from the project root:

    $env:DATABASE_URL = "sqlite+aiosqlite:///./demo.db"
    .venv\\Scripts\\python.exe -m scripts.seed_demo
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import time
from pathlib import Path

from sqlalchemy import insert, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.doctor_dental_service import doctor_dental_services
from app.models.doctor_schedule import DoctorSchedule
from app.models.patient import Patient
from app.models.user import User


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEMO_DB_NAME = "demo.db"

# DEMO-ONLY credentials; documented as test data, never production secrets.
DEMO_ADMIN_PHONE = "09120000001"
DEMO_ADMIN_PASSWORD = "DemoAdmin!123"
DEMO_PATIENT_PHONE = "09120000002"
DEMO_PATIENT_PASSWORD = "DemoPatient!123"
DEMO_PATIENT_NATIONAL_ID = "0012345678"
DEMO_DOCTORS = (
    {
        "name": "دکتر سارا احمدی",
        "phone": "09120000003",
        "specialty": "دندانپزشکی عمومی",
    },
    {
        "name": "دکتر امیر کریمی",
        "phone": "09120000004",
        "specialty": "دندانپزشکی عمومی",
    },
)
DEMO_SERVICES = (
    {
        "name": "معاینه اولیه دندانپزشکی",
        "description": "معاینه و بررسی اولیه دندان و لثه؛ ارجاع درمان به دندانپزشک.",
    },
    {
        "name": "ترمیم دندان",
        "description": "بررسی و ترمیم پوسیدگی یا آسیب دندان توسط دندانپزشک.",
    },
    {
        "name": "جرم‌گیری نمایشی",
        "description": "پاکسازی جرم و پلاک دندان؛ خدمت ساختگی دمو.",
    },
)


def validate_demo_database_url(
    database_url: str | None = None,
    *,
    project_root: Path | None = None,
) -> str:
    """Return the URL only when it points exactly at the demo database."""
    raw = database_url if database_url is not None else os.getenv("DATABASE_URL", "")
    raw = (raw or "").strip()
    if not raw:
        raise SystemExit(
            "DATABASE_URL is not set. Set it to "
            "sqlite+aiosqlite:///./demo.db before running the demo seeder."
        )

    try:
        parsed = make_url(raw)
    except Exception as exc:  # noqa: BLE001 - report a clear, secret-free error
        raise SystemExit("DATABASE_URL is not a valid SQLAlchemy URL.") from exc

    if parsed.get_backend_name() != "sqlite" or not parsed.drivername.startswith(
        "sqlite+aiosqlite"
    ):
        raise SystemExit(
            "The demo seeder only supports SQLite URLs using the aiosqlite driver."
        )

    database = parsed.database
    if not database or database == ":memory:":
        raise SystemExit("The demo seeder refuses an in-memory database.")

    expected = ((project_root or PROJECT_ROOT) / DEMO_DB_NAME).resolve()
    candidate = Path(database)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    if candidate.resolve() != expected:
        raise SystemExit(
            "Refusing to seed an unexpected database. The only allowed target "
            f"is {expected}. No database was modified."
        )
    return raw


async def _get_or_create_user(
    db: AsyncSession,
    *,
    phone: str,
    full_name: str,
    role: str,
    password: str,
) -> tuple[User, bool]:
    user = await db.scalar(select(User).where(User.phone == phone))
    if user is not None:
        if user.role != role:
            raise RuntimeError(
                f"Phone {phone} already belongs to a user with role "
                f"{user.role!r}; expected {role!r}."
            )
        return user, False
    user = User(
        full_name=full_name,
        phone=phone,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user, True


async def seed_demo(db: AsyncSession) -> dict[str, int | bool]:
    """Create the demo fixture once; repeated runs keep row counts stable."""
    try:
        admin, admin_created = await _get_or_create_user(
            db,
            phone=DEMO_ADMIN_PHONE,
            full_name="مدیر نمایشی",
            role="admin",
            password=DEMO_ADMIN_PASSWORD,
        )
        patient_user, patient_user_created = await _get_or_create_user(
            db,
            phone=DEMO_PATIENT_PHONE,
            full_name="بیمار نمایشی",
            role="patient",
            password=DEMO_PATIENT_PASSWORD,
        )

        patient = await db.scalar(
            select(Patient).where(
                Patient.national_id == DEMO_PATIENT_NATIONAL_ID
            )
        )
        patient_created = False
        if patient is None:
            patient = Patient(
                national_id=DEMO_PATIENT_NATIONAL_ID,
                full_name="بیمار نمایشی",
                phone=DEMO_PATIENT_PHONE,
                user_id=patient_user.id,
            )
            db.add(patient)
            await db.flush()
            patient_created = True
        elif patient.user_id is None:
            patient.user_id = patient_user.id
        elif patient.user_id != patient_user.id:
            raise RuntimeError(
                "The demo patient record is linked to a different user; "
                "refusing to change ownership."
            )

        doctors: list[Doctor] = []
        doctors_created = 0
        for doctor_spec in DEMO_DOCTORS:
            doctor = await db.scalar(
                select(Doctor)
                .where(Doctor.phone == doctor_spec["phone"])
                .order_by(Doctor.id)
                .limit(1)
            )
            if doctor is None:
                doctor = Doctor(
                    full_name=doctor_spec["name"],
                    specialty=doctor_spec["specialty"],
                    phone=doctor_spec["phone"],
                    is_active=True,
                )
                db.add(doctor)
                await db.flush()
                doctors_created += 1
            elif not doctor.is_active:
                doctor.is_active = True
            doctors.append(doctor)

        services: list[DentalService] = []
        services_created = 0
        for service_spec in DEMO_SERVICES:
            service = await db.scalar(
                select(DentalService)
                .where(DentalService.name == service_spec["name"])
                .order_by(DentalService.id)
                .limit(1)
            )
            if service is None:
                service = DentalService(
                    name=service_spec["name"],
                    description=service_spec["description"],
                    is_active=True,
                )
                db.add(service)
                await db.flush()
                services_created += 1
            elif not service.is_active:
                service.is_active = True
            services.append(service)

        links_created = 0
        for doctor in doctors:
            for service in services:
                link = await db.scalar(
                    select(doctor_dental_services.c.doctor_id).where(
                        doctor_dental_services.c.doctor_id == doctor.id,
                        doctor_dental_services.c.dental_service_id
                        == service.id,
                    )
                )
                if link is None:
                    await db.execute(
                        insert(doctor_dental_services).values(
                            doctor_id=doctor.id,
                            dental_service_id=service.id,
                        )
                    )
                    links_created += 1

        schedules_created = 0
        for doctor in doctors:
            for day_of_week in range(7):
                existing_schedule = await db.scalar(
                    select(DoctorSchedule.id)
                    .where(
                        DoctorSchedule.doctor_id == doctor.id,
                        DoctorSchedule.day_of_week == day_of_week,
                        DoctorSchedule.is_active.is_(True),
                    )
                    .limit(1)
                )
                if existing_schedule is None:
                    db.add(
                        DoctorSchedule(
                            doctor_id=doctor.id,
                            day_of_week=day_of_week,
                            start_time=time(9),
                            end_time=time(13),
                            slot_duration_minutes=30,
                            is_active=True,
                        )
                    )
                    schedules_created += 1

        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return {
        "admin_id": admin.id,
        "patient_user_id": patient_user.id,
        "patient_id": patient.id,
        "doctor_ids": [doctor.id for doctor in doctors],
        "service_ids": [service.id for service in services],
        "admin_created": admin_created,
        "patient_user_created": patient_user_created,
        "patient_created": patient_created,
        "doctor_created": doctors_created > 0,
        "service_created": services_created > 0,
        "doctors_created": doctors_created,
        "services_created": services_created,
        "links_created": links_created,
        "schedules_created": schedules_created,
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        validate_demo_database_url()
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2

    # Importing app.database initializes the engine from the already-validated
    # DATABASE_URL. No database is opened before this point.
    from app.database import SessionLocal, init_db

    async def _run() -> dict[str, int | bool]:
        await init_db()
        async with SessionLocal() as db:
            return await seed_demo(db)

    try:
        summary = asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 - print a clear error, no secrets
        print(f"Demo seed failed: {exc}", file=sys.stderr)
        return 1

    print("Demo database seeded (idempotent):")
    print(f"  Admin:      {DEMO_ADMIN_PHONE} / {DEMO_ADMIN_PASSWORD}  [DEMO ONLY]")
    print(f"  Patient:    {DEMO_PATIENT_PHONE} (OTP login)          [DEMO ONLY]")
    print(f"  Doctors:    {len(DEMO_DOCTORS)} (all weekdays 09:00-13:00)")
    print(f"  Services:   {', '.join(item['name'] for item in DEMO_SERVICES)}")
    print(f"  Schedules:  {summary['schedules_created']} new")
    print(
        "  Example:    نزدیک‌ترین نوبت برای جرم‌گیری نمایشی را پیدا کن و "
        "برای دکتر سارا احمدی پیشنهاد بده."
    )
    print("  Chat demo:  http://127.0.0.1:8000/demo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
