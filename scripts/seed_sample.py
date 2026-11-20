"""Idempotent sample clinic data for a local, production-shaped dataset.

Safety contract:
- Requires an explicit ``DATABASE_URL`` that resolves exactly to the project's
  ``sample.db``. Any other path (including the real ``dental_agent.db``) is
  rejected before any database connection is opened.
- Only creates missing rows; it never deletes, truncates, or resets a database.
- Accounts and records are fictional sample data with non-production passwords.

Run from the project root:

    $env:DATABASE_URL = "sqlite+aiosqlite:///./sample.db"
    .venv\\Scripts\\python.exe -m scripts.seed_sample
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, insert, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password
from app.models.appointment import Appointment
from app.models.clinical_entry import ClinicalEntry
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.doctor_dental_service import doctor_dental_services
from app.models.doctor_schedule import DoctorSchedule
from app.models.patient import Patient
from app.models.prescription import Prescription
from app.models.tooth_status import ToothStatus
from app.models.treatment_plan import TreatmentPlanItem
from app.models.user import User

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DB_NAME = "sample.db"

# Fictional clinic accounts with non-production passwords, used only by the
# local sample database. Real deployments create accounts through the admin UI.
SAMPLE_ADMIN_PHONE = "09121234500"
SAMPLE_ADMIN_PASSWORD = "ClinicAdmin!1404"
SAMPLE_PATIENT_PHONE = "09121234510"
SAMPLE_PATIENT_PASSWORD = "ClinicPatient!1404"
SAMPLE_PATIENT_NATIONAL_ID = "0079854123"
SAMPLE_RECEPTIONIST_PHONE = "09121234501"
SAMPLE_RECEPTIONIST_PASSWORD = "ClinicDesk!1404"
SAMPLE_DOCTOR_USER_PHONE = "09121234502"
SAMPLE_DOCTOR_USER_PASSWORD = "ClinicDoctor!1404"
SAMPLE_DOCTORS = (
    {
        "name": "دکتر سارا احمدی",
        "phone": "09121234502",
        "specialty": "دندانپزشکی عمومی",
    },
    {
        "name": "دکتر امیر کریمی",
        "phone": "09121234503",
        "specialty": "دندانپزشکی عمومی",
    },
)
SAMPLE_SERVICES = (
    {
        "name": "معاینه اولیه دندانپزشکی",
        "description": "معاینه و بررسی اولیه دندان و لثه؛ ارجاع درمان به دندانپزشک.",
    },
    {
        "name": "ترمیم دندان",
        "description": "بررسی و ترمیم پوسیدگی یا آسیب دندان توسط دندانپزشک.",
    },
    {
        "name": "جرم‌گیری و پاکسازی",
        "description": "پاکسازی جرم و پلاک دندان با دستگاه اولتراسونیک.",
    },
)


def validate_sample_database_url(
    database_url: str | None = None,
    *,
    project_root: Path | None = None,
) -> str:
    """Return the URL only when it points exactly at the sample database."""
    raw = database_url if database_url is not None else os.getenv("DATABASE_URL", "")
    raw = (raw or "").strip()
    if not raw:
        raise SystemExit(
            "DATABASE_URL is not set. Set it to "
            "sqlite+aiosqlite:///./sample.db before running the sample seeder."
        )

    try:
        parsed = make_url(raw)
    except Exception as exc:  # noqa: BLE001 - report a clear, secret-free error
        raise SystemExit("DATABASE_URL is not a valid SQLAlchemy URL.") from exc

    if parsed.get_backend_name() != "sqlite" or not parsed.drivername.startswith(
        "sqlite+aiosqlite"
    ):
        raise SystemExit(
            "The sample seeder only supports SQLite URLs using the aiosqlite driver."
        )

    database = parsed.database
    if not database or database == ":memory:":
        raise SystemExit("The sample seeder refuses an in-memory database.")

    expected = ((project_root or PROJECT_ROOT) / SAMPLE_DB_NAME).resolve()
    candidate = Path(database)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    if candidate.resolve() != expected:
        raise SystemExit(
            "Refusing to seed an unexpected database. The only allowed target "
            f"is {expected}. No database was modified."
        )
    return raw


# Additional patients so the clinic day and clinical records look populated.
# Fictional records; phone numbers live in reserved, non-routable sample ranges.
SAMPLE_EXTRA_PATIENTS = (
    ("پریسا محمدی", "09361234011", "0071234011"),
    ("رضا عبدی", "09361234012", "0071234012"),
    ("مریم حسینی", "09361234013", "0071234013"),
    ("حسین رضایی", "09361234014", "0071234014"),
    ("سعید نیکزاد", "09361234015", "0071234015"),
    ("فاطمه شریفی", "09361234016", "0071234016"),
    ("امیر توکلی", "09361234017", "0071234017"),
    ("نگار سلطانی", "09361234018", "0071234018"),
    ("مهدی زمانی", "09361234019", "0071234019"),
    ("زهرا کاظمی", "09361234020", "0071234020"),
)

# One realistic clinic day. Offsets are minutes relative to the seeder's
# "now" (clamped to clinic hours) so the snapshot always looks current:
# ``flow`` drives the status/timestamps and ``queue`` is the arrival number
# the front desk would have assigned. Numbers are per doctor (each room counts
# its own), so doctor 0 and doctor 1 both start from 1.
SAMPLE_DAY_APPOINTMENTS = (
    ("پریسا محمدی", 0, -150, 0, "completed", "معاینه و بررسی اولیه", 1),
    ("رضا عبدی", 0, -110, 1, "completed", "ترمیم دندان عقل", 2),
    ("فاطمه شریفی", 1, -160, 0, "no_show", "معاینه اولیه", None),
    ("امیر توکلی", 1, -90, 2, "cancelled", "جرم‌گیری", None),
    ("نگار سلطانی", 1, -55, 1, "waiting", "شکستگی دندان ۲۱", 1),
    ("حسین رضایی", 0, -45, 2, "waiting", "جرم‌گیری دوره‌ای", 3),
    ("مریم حسینی", 0, -25, 1, "in_progress", "درد دندان ۴۶", 4),
    ("سعید نیکزاد", 0, 35, 1, "scheduled", "ترمیم دندان ۱۶", None),
    ("مهدی زمانی", 1, 80, 0, "scheduled", "معاینه", None),
    ("زهرا کاظمی", 1, 125, 0, "scheduled", "مشاوره درمان", None),
)

SAMPLE_CLINICAL_DATA = {
    "پریسا محمدی": {
        "teeth": ((16, "treated", "ترمیم کامپوزیت"), (26, "needs_treatment", "پوسیدگی سطحی")),
        "entries": (
            ("treatment", 16, "ترمیم کامپوزیت اکلوزال", "پوسیدگی اکلوزال پاک‌سازی و ترمیم شد."),
            ("note", None, "یادداشت جلسه", "بیمار به حساسیت پس از درمان توصیه شد."),
        ),
        "prescriptions": (
            ([{"name": "استامینوفن", "dose": "۵۰۰ میلی‌گرم", "frequency": "هر ۸ ساعت", "duration": "۳ روز"}], "در صورت درد مصرف شود."),
        ),
        "plan": (("ترمیم کامپوزیت", 26, "planned"),),
    },
    "رضا عبدی": {
        "teeth": ((36, "treated", "عصب‌کشی و ترمیم"), (37, "needs_treatment", "پوسیدگی عمیق")),
        "entries": (
            ("treatment", 36, "درمان ریشه", "درمان ریشه در دو جلسه تکمیل شد."),
            ("note", None, "توصیه پس از درمان", "پرهیز از غذای سخت روی دندان ۳۶ تا یک هفته."),
        ),
        "prescriptions": (
            ([{"name": "آموکسی‌سیلین", "dose": "۵۰۰ میلی‌گرم", "frequency": "هر ۸ ساعت", "duration": "۵ روز"}], None),
            ([{"name": "ایبوپروفن", "dose": "۴۰۰ میلی‌گرم", "frequency": "هر ۶ ساعت", "duration": "۲ روز"}], "همراه غذا مصرف شود."),
        ),
        "plan": (("روکش سرامیکی", 36, "in_progress"), ("ترمیم کامپوزیت", 37, "planned")),
    },
    "مریم حسینی": {
        "teeth": ((46, "needs_treatment", "درد حاد"), (47, "extracted", "کشیده شده")),
        "entries": (
            ("allergy", None, "حساسیت به پنی‌سیلین", "واکنش آلرژیک در سابقه؛ آنتی‌بیوتیک جایگزین تجویز شود."),
            ("treatment", 46, "شروع درمان ریشه", "جلسه اول؛ کانال‌ها آماده‌سازی شد."),
        ),
        "prescriptions": (
            ([{"name": "کلیندامایسین", "dose": "۳۰۰ میلی‌گرم", "frequency": "هر ۸ ساعت", "duration": "۴ روز"}], "به دلیل حساسیت به پنی‌سیلین."),
        ),
        "plan": (("ادامه درمان ریشه", 46, "in_progress"),),
    },
    "نگار سلطانی": {
        "teeth": ((21, "needs_treatment", "شکستگی"), (11, "treated", "کامپوزیت")),
        "entries": (
            ("treatment", 21, "ترمیم شکستگی", "ترمیم زیبایی کامپوزیت انجام شد."),
        ),
        "prescriptions": (),
        "plan": (("ترمیم نهایی", 21, "planned"),),
    },
    "حسین رضایی": {
        "teeth": ((16, "healthy", None), (17, "treated", "جرم‌گیری")),
        "entries": (
            ("note", None, "وضعیت لثه", "التهاب خفیف لثه؛ جرم‌گیری دوره‌ای توصیه شد."),
        ),
        "prescriptions": (),
        "plan": (("جرم‌گیری کامل", None, "planned"),),
    },
}


async def _get_or_create_patient(
    db: AsyncSession,
    *,
    full_name: str,
    phone: str,
    national_id: str,
) -> tuple[Patient, bool]:
    patient = await db.scalar(
        select(Patient).where(Patient.national_id == national_id)
    )
    if patient is not None:
        return patient, False
    patient = Patient(
        national_id=national_id,
        full_name=full_name,
        phone=phone,
    )
    db.add(patient)
    await db.flush()
    return patient, True


def _clinic_today() -> datetime:
    return datetime.now(ZoneInfo("Asia/Tehran")).replace(tzinfo=None)


async def seed_clinic_flow(
    db: AsyncSession,
    *,
    doctors: list[Doctor],
    services: list[DentalService],
    admin: User,
    doctor_user: User,
) -> dict[str, int]:
    """Populate one realistic clinic day plus sample clinical records.

    Idempotent by natural key: appointments are matched on
    (patient, day), tooth rows on (patient, tooth), and clinical tables
    only get seeded for a patient that has none yet. Nothing is deleted or
    updated, so repeated runs leave the database unchanged.
    """
    patients: dict[str, Patient] = {}
    patients_created = 0
    for full_name, phone, national_id in SAMPLE_EXTRA_PATIENTS:
        patient, created = await _get_or_create_patient(
            db, full_name=full_name, phone=phone, national_id=national_id
        )
        patients[full_name] = patient
        patients_created += 1 if created else 0

    now = _clinic_today()
    today = now.date()
    # Anchor the schedule on the seeder run so the snapshot looks current, but
    # clamp it so that every appointment lands inside clinic hours regardless
    # of when the seeder happens to run (e.g. midnight).
    earliest = min(row[2] for row in SAMPLE_DAY_APPOINTMENTS)
    latest = max(row[2] for row in SAMPLE_DAY_APPOINTMENTS)
    anchor_min = datetime.combine(today, time(9)) - timedelta(minutes=earliest)
    anchor_max = datetime.combine(today, time(18)) - timedelta(minutes=latest)
    anchor = min(max(now, anchor_min), anchor_max)
    day_start = datetime.combine(today, time(0))
    day_end = day_start + timedelta(days=1)
    appointments_created = 0
    appointment_ids: dict[str, int] = {}
    for (
        patient_name,
        doctor_index,
        offset_minutes,
        service_index,
        flow,
        reason,
        queue,
    ) in SAMPLE_DAY_APPOINTMENTS:
        patient = patients[patient_name]
        doctor = doctors[doctor_index]
        service = services[service_index]
        slot = (anchor + timedelta(minutes=offset_minutes)).replace(
            second=0, microsecond=0
        )

        # Match on (patient, day) instead of the exact minute: re-running the
        # seeder a few minutes later must not append a second copy of the
        # same patient's visit.
        existing_id = await db.scalar(
            select(Appointment.id).where(
                Appointment.patient_id == patient.id,
                Appointment.appointment_time >= day_start,
                Appointment.appointment_time < day_end,
            )
        )
        if existing_id is not None:
            appointment_ids[patient_name] = existing_id
            continue

        appointment = Appointment(
            patient_id=patient.id,
            doctor_id=doctor.id,
            service_id=service.id,
            appointment_time=slot,
            status="scheduled",
            reason=reason,
        )

        if flow == "completed":
            appointment.status = "completed"
            appointment.checked_in_at = slot + timedelta(minutes=6)
            appointment.started_at = slot + timedelta(minutes=12)
            appointment.completed_at = slot + timedelta(minutes=40)
        elif flow == "in_progress":
            appointment.status = "in_progress"
            appointment.checked_in_at = slot + timedelta(minutes=4)
            appointment.started_at = slot + timedelta(minutes=15)
        elif flow == "waiting":
            appointment.checked_in_at = slot + timedelta(minutes=3)
        elif flow == "no_show":
            appointment.status = "no_show"
            appointment.completed_at = slot + timedelta(minutes=20)
        elif flow == "cancelled":
            appointment.status = "cancelled"

        if queue is not None:
            appointment.queue_number = queue

        db.add(appointment)
        await db.flush()
        appointment_ids[patient_name] = appointment.id
        appointments_created += 1

    teeth_created = 0
    entries_created = 0
    prescriptions_created = 0
    plan_items_created = 0

    for patient_name, data in SAMPLE_CLINICAL_DATA.items():
        patient = patients[patient_name]
        appointment_id = appointment_ids.get(patient_name)
        doctor_id = doctors[0].id if patient_name != "نگار سلطانی" else doctors[1].id

        for tooth_fdi, status, note in data["teeth"]:
            exists = await db.scalar(
                select(ToothStatus.id).where(
                    ToothStatus.patient_id == patient.id,
                    ToothStatus.tooth_fdi == tooth_fdi,
                )
            )
            if exists is None:
                db.add(
                    ToothStatus(
                        patient_id=patient.id,
                        tooth_fdi=tooth_fdi,
                        status=status,
                        note=note,
                        updated_by_user_id=admin.id,
                        updated_at=now,
                    )
                )
                teeth_created += 1

        existing_entries = await db.scalar(
            select(func.count(ClinicalEntry.id)).where(
                ClinicalEntry.patient_id == patient.id
            )
        )
        if not existing_entries:
            for kind, tooth_fdi, title, body in data["entries"]:
                db.add(
                    ClinicalEntry(
                        patient_id=patient.id,
                        doctor_id=doctor_id,
                        appointment_id=appointment_id,
                        kind=kind,
                        tooth_fdi=tooth_fdi,
                        title=title,
                        body=body,
                        created_by_user_id=doctor_user.id,
                        created_at=now,
                    )
                )
                entries_created += 1

        existing_prescriptions = await db.scalar(
            select(func.count(Prescription.id)).where(
                Prescription.patient_id == patient.id
            )
        )
        if not existing_prescriptions:
            for items, notes in data["prescriptions"]:
                db.add(
                    Prescription(
                        patient_id=patient.id,
                        doctor_id=doctor_id,
                        appointment_id=appointment_id,
                        items=items,
                        notes=notes,
                        created_by_user_id=doctor_user.id,
                        created_at=now,
                    )
                )
                prescriptions_created += 1

        existing_plan = await db.scalar(
            select(func.count(TreatmentPlanItem.id)).where(
                TreatmentPlanItem.patient_id == patient.id
            )
        )
        if not existing_plan:
            for title, tooth_fdi, status in data["plan"]:
                db.add(
                    TreatmentPlanItem(
                        patient_id=patient.id,
                        doctor_id=doctor_id,
                        tooth_fdi=tooth_fdi,
                        title=title,
                        status=status,
                        created_by_user_id=doctor_user.id,
                        created_at=now,
                        updated_at=now,
                    )
                )
                plan_items_created += 1

    return {
        "patients_created": patients_created,
        "appointments_created": appointments_created,
        "teeth_created": teeth_created,
        "entries_created": entries_created,
        "prescriptions_created": prescriptions_created,
        "plan_items_created": plan_items_created,
    }


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


async def seed_sample(db: AsyncSession) -> dict[str, int | bool]:
    """Create the sample fixture once; repeated runs keep row counts stable."""
    try:
        admin, admin_created = await _get_or_create_user(
            db,
            phone=SAMPLE_ADMIN_PHONE,
            full_name="سمیرا موسوی",
            role="admin",
            password=SAMPLE_ADMIN_PASSWORD,
        )
        patient_user, patient_user_created = await _get_or_create_user(
            db,
            phone=SAMPLE_PATIENT_PHONE,
            full_name="نیلوفر احمدی",
            role="patient",
            password=SAMPLE_PATIENT_PASSWORD,
        )
        receptionist, receptionist_created = await _get_or_create_user(
            db,
            phone=SAMPLE_RECEPTIONIST_PHONE,
            full_name="نگین شریفی",
            role="receptionist",
            password=SAMPLE_RECEPTIONIST_PASSWORD,
        )
        doctor_user, doctor_user_created = await _get_or_create_user(
            db,
            phone=SAMPLE_DOCTOR_USER_PHONE,
            full_name="دکتر سارا احمدی",
            role="doctor",
            password=SAMPLE_DOCTOR_USER_PASSWORD,
        )

        patient = await db.scalar(
            select(Patient).where(
                Patient.national_id == SAMPLE_PATIENT_NATIONAL_ID
            )
        )
        patient_created = False
        if patient is None:
            patient = Patient(
                national_id=SAMPLE_PATIENT_NATIONAL_ID,
                full_name="نیلوفر احمدی",
                phone=SAMPLE_PATIENT_PHONE,
                user_id=patient_user.id,
            )
            db.add(patient)
            await db.flush()
            patient_created = True
        elif patient.user_id is None:
            patient.user_id = patient_user.id
        elif patient.user_id != patient_user.id:
            raise RuntimeError(
                "The sample patient record is linked to a different user; "
                "refusing to change ownership."
            )

        doctors: list[Doctor] = []
        doctors_created = 0
        for doctor_spec in SAMPLE_DOCTORS:
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

        # Link the sample doctor account to the first doctor record (1:1).
        if doctors and doctors[0].user_id is None:
            doctors[0].user_id = doctor_user.id
        elif doctors and doctors[0].user_id not in (None, doctor_user.id):
            raise RuntimeError(
                "The sample doctor record is linked to a different user; "
                "refusing to change ownership."
            )

        services: list[DentalService] = []
        services_created = 0
        for service_spec in SAMPLE_SERVICES:
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

        clinic_summary = await seed_clinic_flow(
            db,
            doctors=doctors,
            services=services,
            admin=admin,
            doctor_user=doctor_user,
        )

        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return {
        **clinic_summary,
        "admin_id": admin.id,
        "patient_user_id": patient_user.id,
        "receptionist_id": receptionist.id,
        "doctor_user_id": doctor_user.id,
        "patient_id": patient.id,
        "doctor_ids": [doctor.id for doctor in doctors],
        "service_ids": [service.id for service in services],
        "admin_created": admin_created,
        "patient_user_created": patient_user_created,
        "receptionist_created": receptionist_created,
        "doctor_user_created": doctor_user_created,
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
        validate_sample_database_url()
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2

    # Importing app.database initializes the engine from the already-validated
    # DATABASE_URL. No database is opened before this point.
    from app.database import SessionLocal, init_db

    async def _run() -> dict[str, int | bool]:
        await init_db()
        async with SessionLocal() as db:
            return await seed_sample(db)

    try:
        summary = asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 - print a clear error, no secrets
        print(f"Sample seed failed: {exc}", file=sys.stderr)
        return 1

    print("Sample clinic database seeded (idempotent):")
    print(f"  Admin:        {SAMPLE_ADMIN_PHONE} / {SAMPLE_ADMIN_PASSWORD}")
    print(f"  Receptionist: {SAMPLE_RECEPTIONIST_PHONE} / {SAMPLE_RECEPTIONIST_PASSWORD}")
    print(f"  Doctor login: {SAMPLE_DOCTOR_USER_PHONE} / {SAMPLE_DOCTOR_USER_PASSWORD}")
    print(f"  Patient:      {SAMPLE_PATIENT_PHONE} (OTP login)")
    print(f"  Doctors:      {len(SAMPLE_DOCTORS)} (all weekdays 09:00-13:00)")
    print(f"  Services:     {', '.join(item['name'] for item in SAMPLE_SERVICES)}")
    print(f"  Schedules:    {summary['schedules_created']} new")
    print(
        "  Clinic day:   "
        f"{summary['appointments_created']} appointments, "
        f"{summary['patients_created']} patients, "
        f"{summary['entries_created']} entries, "
        f"{summary['teeth_created']} tooth rows, "
        f"{summary['prescriptions_created']} prescriptions, "
        f"{summary['plan_items_created']} plan items"
    )
    print(
        "  Example:      نزدیک‌ترین نوبت برای جرم‌گیری را پیدا کن و "
        "برای دکتر سارا احمدی پیشنهاد بده."
    )
    print("  Patient app:  http://127.0.0.1:8000/app")
    print("  Staff portal: http://127.0.0.1:8000/staff")
    return 0


if __name__ == "__main__":
    sys.exit(main())
