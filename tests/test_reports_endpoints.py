"""End-to-end tests for the admin `/reports/dashboard` endpoint.

The dashboard must be admin-only and every number must be a real SQL
aggregate that moves exactly with rows created (and cleaned up) by these
tests. Baseline deltas keep the assertions independent of other test files
sharing the process-wide database.
"""

import asyncio
import os
import unittest
from datetime import timedelta

# Set test environment variables BEFORE importing app modules.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only-32-chars-long"
os.environ["JWT_ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"
os.environ["CONFIRMATION_HMAC_SECRET"] = (
    "test-confirmation-hmac-secret-32-chars-long"
)
os.environ["CONFIRMATION_TTL_SECONDS"] = "300"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from app.auth.security import create_access_token, hash_password  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.appointment import Appointment  # noqa: E402
from app.models.dental_service import DentalService  # noqa: E402
from app.models.doctor import Doctor  # noqa: E402
from app.models.patient import Patient  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.appointment_service import clinic_now  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


_PROBE_PHONES = {
    "admin": "09380006001",
    "receptionist": "09380006002",
    "doctor": "09380006003",
    "patient": "09380006004",
}


def _create_role_user(role):
    async def _create():
        async with SessionLocal() as db:
            user = User(
                full_name="Reports Probe",
                phone=_PROBE_PHONES[role],
                password_hash=hash_password("probe-pass-123"),
                role=role,
                is_active=True,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            return user

    return _run(_create())


def _delete_probe_users():
    async def _delete():
        async with SessionLocal() as db:
            await db.execute(
                delete(User).where(User.phone.in_(_PROBE_PHONES.values()))
            )
            await db.commit()

    _run(_delete())


def _delete_probe_rows(doctor_id):
    """Remove rows created by this test file only (all names carry the tag)."""

    async def _delete():
        async with SessionLocal() as db:
            appointments = (
                await db.execute(
                    select(Appointment).where(Appointment.doctor_id == doctor_id)
                )
            ).scalars().all()
            for row in appointments:
                await db.delete(row)
            doctor = await db.get(Doctor, doctor_id)
            if doctor is not None:
                await db.delete(doctor)
            for patient in (
                await db.execute(
                    select(Patient).where(
                        Patient.full_name.in_(["گزارش بیمار ۱", "گزارش بیمار ۲"])
                    )
                )
            ).scalars().all():
                await db.delete(patient)
            for service in (
                await db.execute(
                    select(DentalService).where(
                        DentalService.name == "خدمت گزارش‌گیری"
                    )
                )
            ).scalars().all():
                await db.delete(service)
            await db.commit()

    _run(_delete())


def _doctor_load_entry(appointments_block, doctor_id):
    for entry in appointments_block["doctor_load"]:
        if entry["doctor_id"] == doctor_id:
            return entry
    return None


class ReportsEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _run(init_db())

    def setUp(self):
        self.client = TestClient(app)
        _delete_probe_users()
        self.admin = _create_role_user("admin")
        self.receptionist = _create_role_user("receptionist")
        self.doctor_user = _create_role_user("doctor")
        self.patient_user = _create_role_user("patient")
        self.tokens = {
            role: create_access_token(subject=str(user.id))
            for role, user in (
                ("admin", self.admin),
                ("receptionist", self.receptionist),
                ("doctor", self.doctor_user),
                ("patient", self.patient_user),
            )
        }
        self.doctor_id = None

    def tearDown(self):
        if self.doctor_id is not None:
            _delete_probe_rows(self.doctor_id)
        _delete_probe_users()

    def _get_dashboard(self, role=None):
        headers = (
            {"Authorization": f"Bearer {self.tokens[role]}"} if role else {}
        )
        return self.client.get("/reports/dashboard", headers=headers)

    def _create_probe_rows(self):
        """Create a deterministic clinic dataset tagged for cleanup."""
        now = clinic_now()
        today_10 = now.replace(hour=10, minute=0, second=0, microsecond=0)

        async def _create():
            async with SessionLocal() as db:
                service = DentalService(
                    name="خدمت گزارش‌گیری",
                    description=None,
                    is_active=True,
                )
                db.add(service)
                doctor = Doctor(
                    full_name="دکتر گزارش",
                    specialty="عمومی",
                    phone="02133445566",
                    is_active=True,
                )
                db.add(doctor)
                complete_patient = Patient(
                    national_id="1000808001",
                    full_name="گزارش بیمار ۱",
                    phone="09380006101",
                    record_status="complete",
                )
                incomplete_patient = Patient(
                    national_id=None,
                    full_name="گزارش بیمار ۲",
                    phone="09380006102",
                    record_status="incomplete",
                )
                db.add_all([complete_patient, incomplete_patient])
                await db.flush()
                rows = [
                    Appointment(
                        patient_id=complete_patient.id,
                        doctor_id=doctor.id,
                        service_id=service.id,
                        appointment_time=today_10,
                        status="scheduled",
                    ),
                    Appointment(
                        patient_id=complete_patient.id,
                        doctor_id=doctor.id,
                        service_id=service.id,
                        appointment_time=today_10 + timedelta(days=3, minutes=30),
                        status="scheduled",
                    ),
                    # A cancellation in the past 30 days (lost yesterday slot).
                    Appointment(
                        patient_id=complete_patient.id,
                        doctor_id=doctor.id,
                        service_id=service.id,
                        appointment_time=today_10 - timedelta(days=2),
                        status="cancelled",
                    ),
                    # A cancellation that happened for an upcoming slot.
                    Appointment(
                        patient_id=complete_patient.id,
                        doctor_id=doctor.id,
                        service_id=service.id,
                        appointment_time=today_10 + timedelta(days=5, minutes=90),
                        status="cancelled",
                    ),
                ]
                db.add_all(rows)
                await db.commit()
                await db.refresh(doctor)
                return doctor.id

        self.doctor_id = _run(_create())

    def test_dashboard_is_admin_only(self):
        self.assertEqual(self._get_dashboard().status_code, 401)
        self.assertEqual(self._get_dashboard("receptionist").status_code, 403)
        self.assertEqual(self._get_dashboard("doctor").status_code, 403)
        self.assertEqual(self._get_dashboard("patient").status_code, 403)
        self.assertEqual(self._get_dashboard("admin").status_code, 200)

    def test_dashboard_aggregates_move_exactly_with_real_rows(self):
        base = self._get_dashboard("admin")
        self.assertEqual(base.status_code, 200)
        before = base.json()
        before_overview = before["overview"]
        before_doctors = {
            entry["doctor_id"]: entry["scheduled_count"]
            for entry in before["appointments"]["doctor_load"]
        }

        self._create_probe_rows()

        try:
            after = self._get_dashboard("admin").json()
            overview = after["overview"]
            appointments = after["appointments"]

            # Patients: one complete + one incomplete added.
            self.assertEqual(
                overview["patients_total"],
                before_overview["patients_total"] + 2,
            )
            self.assertEqual(
                overview["patients_incomplete"],
                before_overview["patients_incomplete"] + 1,
            )
            # Exactly one active doctor added.
            self.assertEqual(
                overview["doctors_total"],
                before_overview["doctors_total"] + 1,
            )
            # One active service added.
            self.assertEqual(
                overview["services_total"],
                before_overview["services_total"] + 1,
            )
            # Two scheduled rows (today + day 3) inside every window.
            self.assertEqual(
                overview["appointments_upcoming"],
                before_overview["appointments_upcoming"] + 2,
            )
            self.assertEqual(
                overview["appointments_today"],
                before_overview["appointments_today"] + 1,
            )
            # Only the past cancellation moves the historical counter (2 days
            # ago); the future one is reported via upcoming_cancelled only.
            self.assertEqual(
                overview["cancellations_30d"],
                before_overview["cancellations_30d"] + 1,
            )
            # The scheduled rows: one today plus one on day +3.
            self.assertEqual(appointments["today_appointments"], 1)
            self.assertEqual(appointments["upcoming_scheduled"], 2)
            # Only the future cancellation lands in the upcoming window; the
            # past one moves the historical cancellation counter instead.
            self.assertEqual(appointments["upcoming_cancelled"], 1)
            self.assertEqual(
                overview["cancellations_30d"],
                before_overview["cancellations_30d"] + 1,
            )

            entry = _doctor_load_entry(appointments, self.doctor_id)
            self.assertIsNotNone(entry)
            self.assertEqual(entry["doctor_name"], "دکتر گزارش")
            self.assertEqual(entry["scheduled_count"], 2)
            # Rows deleted in previous runs never leak into this snapshot.
            self.assertNotIn(self.doctor_id, before_doctors)
        finally:
            _delete_probe_rows(self.doctor_id)
            self.doctor_id = None
            restored = self._get_dashboard("admin").json()
            self.assertEqual(
                restored["overview"]["patients_total"],
                before_overview["patients_total"],
            )

    def test_agent_report_tools_follow_the_role_matrix(self):
        """The same authorization choke point guards the agent tool layer.

        The appointments report is available to staff roles; the whole-clinic
        overview is admin-only and patient accounts are refused before any
        database access happens. Real probe rows provide a determinate
        baseline for the successful calls.
        """
        from app.agent_tools import tools

        async def _appointments_report(actor):
            async with SessionLocal() as db:
                return await tools.get_clinic_appointments_report(
                    db, window_days=7, actor=actor
                )

        async def _overview_stats(actor):
            async with SessionLocal() as db:
                return await tools.get_clinic_overview_stats(db, actor=actor)

        # Refusal happens before any query; verify with an empty snapshot.
        appointments_patient = _run(_appointments_report(self.patient_user))
        self.assertFalse(appointments_patient.ok)
        self.assertEqual(
            appointments_patient.error.code, "COMMON_FORBIDDEN"
        )
        self.assertIsNone(appointments_patient.data)

        overview_receptionist = _run(_overview_stats(self.receptionist))
        self.assertFalse(overview_receptionist.ok)
        self.assertEqual(overview_receptionist.error.code, "COMMON_FORBIDDEN")

        overview_doctor = _run(_overview_stats(self.doctor_user))
        self.assertFalse(overview_doctor.ok)
        self.assertEqual(overview_doctor.error.code, "COMMON_FORBIDDEN")

        overview_patient = _run(_overview_stats(self.patient_user))
        self.assertFalse(overview_patient.ok)
        self.assertEqual(overview_patient.error.code, "COMMON_FORBIDDEN")

        # Real rows so the allowed calls return fully populated data.
        try:
            before = _run(_overview_stats(self.admin))
            self.assertTrue(before.ok)
            self._create_probe_rows()
            appointments_admin = _run(_appointments_report(self.admin))
            self.assertTrue(appointments_admin.ok)
            self.assertFalse(appointments_admin.error)

            appointments_receptionist = _run(
                _appointments_report(self.receptionist)
            )
            self.assertTrue(appointments_receptionist.ok)

            appointments_doctor = _run(_appointments_report(self.doctor_user))
            self.assertTrue(appointments_doctor.ok)

            after = _run(_overview_stats(self.admin))
            self.assertTrue(after.ok)
            self.assertEqual(
                after.data.patients_total, before.data.patients_total + 2
            )
            self.assertEqual(
                after.data.patients_incomplete,
                before.data.patients_incomplete + 1,
            )
            self.assertEqual(
                after.data.doctors_total, before.data.doctors_total + 1
            )
            self.assertEqual(
                after.data.services_total, before.data.services_total + 1
            )
        finally:
            _delete_probe_rows(self.doctor_id)
            self.doctor_id = None


if __name__ == "__main__":
    unittest.main()
