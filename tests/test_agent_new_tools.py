"""Role-scoped access and behavior of the new agent tools.

Covers the 2026-10-30 tool expansion: ``search_patients``,
``get_patient_summary``, ``get_doctor_schedules``, ``get_doctor_day_plan``
and ``get_user_reports_summary``. Handlers are called directly (same
boundary style as ``test_agent_tool_authorization.py``) plus registry
consistency checks so a future tool can never ship without an action
mapping.
"""

import unittest
from datetime import datetime, time
from unittest.mock import patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agent.registry import TOOL_REGISTRY
from app.agent_tools import tools
from app.auth.permissions import _TOOL_ACTIONS, effective_permissions
from app.models.appointment import Appointment
from app.models.base import Base
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.doctor_schedule import DoctorSchedule
from app.models.feedback import FeedbackReport
from app.models.patient import Patient
from app.models.user import User
from app.services import appointment_service


def _user(role: str, phone: str) -> User:
    return User(
        full_name=f"کاربر {role} {phone}",
        phone=phone,
        password_hash="unused",
        role=role,
        is_active=True,
    )


class AgentNewToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False
        )
        self.db = self.session_factory()

        self.admin = _user("admin", "09930000001")
        self.receptionist = _user("receptionist", "09930000002")
        self.doctor_user = _user("doctor", "09930000003")
        self.other_doctor_user = _user("doctor", "09930000004")
        self.patient_user = _user("patient", "09930000005")
        self.db.add_all(
            [
                self.admin,
                self.receptionist,
                self.doctor_user,
                self.other_doctor_user,
                self.patient_user,
            ]
        )
        await self.db.flush()

        self.patient = Patient(
            national_id="2000000042",
            full_name="مریض نمونه",
            phone="09930000005",
            user_id=self.patient_user.id,
            is_account_holder=True,
        )
        self.other_patient = Patient(
            national_id="2000000043",
            full_name="بیمار دیگر",
            phone="09930000006",
        )
        self.doctor = Doctor(
            full_name="دکتر اول",
            specialty="دندانپزشکی عمومی",
            phone="09930000007",
            user_id=self.doctor_user.id,
            is_active=True,
        )
        self.other_doctor = Doctor(
            full_name="دکتر دوم",
            specialty="ارتودنسی",
            phone="09930000008",
            user_id=self.other_doctor_user.id,
            is_active=True,
        )
        self.service = DentalService(name="جرم‌گیری", is_active=True)
        self.db.add_all(
            [self.patient, self.other_patient, self.doctor, self.other_doctor, self.service]
        )
        await self.db.flush()

        self.db.add_all(
            [
                DoctorSchedule(
                    doctor_id=self.doctor.id,
                    day_of_week=5,
                    start_time=time(8, 0),
                    end_time=time(12, 0),
                    slot_duration_minutes=30,
                    is_active=True,
                ),
                DoctorSchedule(
                    doctor_id=self.doctor.id,
                    day_of_week=6,
                    start_time=time(16, 0),
                    end_time=time(18, 0),
                    slot_duration_minutes=20,
                    is_active=True,
                ),
            ]
        )
        # Thursday 2026-10-08 08:00 Tehran-ish clinic clock; fixed for
        # deterministic "today" resolution and upcoming/past separation.
        self._real_clinic_now = appointment_service.clinic_now
        self._now_patcher = patch.object(
            appointment_service,
            "clinic_now",
            side_effect=lambda now=None: self._real_clinic_now(
                datetime(2026, 10, 8, 8, 0) if now is None else now
            ),
        )
        self._now_patcher.start()
        self.addCleanup(self._now_patcher.stop)
        await self.db.flush()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _book(
        self,
        patient: Patient,
        doctor: Doctor,
        when: datetime,
        status: str = "scheduled",
    ) -> Appointment:
        appointment = Appointment(
            patient_id=patient.id,
            doctor_id=doctor.id,
            service_id=self.service.id,
            appointment_time=when,
            status=status,
            reason="درد خفیف" if status == "scheduled" else None,
        )
        self.db.add(appointment)
        await self.db.flush()
        return appointment

    # ------------------------------------------------------------------
    # search_patients
    # ------------------------------------------------------------------

    async def test_search_patients_masks_national_id_for_staff(self):
        result = await tools.search_patients(
            self.db, "مریض", actor=self.receptionist
        )
        self.assertTrue(result.ok)
        row = result.data[0]
        self.assertEqual(row.full_name, "مریض نمونه")
        self.assertEqual(row.phone, "09930000005")
        self.assertTrue(row.national_id_masked.startswith("***"))
        self.assertNotIn("2000000042", result.model_dump_json())

    async def test_search_patients_role_matrix_and_overrides(self):
        for actor in (self.admin, self.receptionist, self.doctor_user):
            result = await tools.search_patients(self.db, actor=actor)
            self.assertTrue(result.ok)
        # Patient role is never allowed a clinic-wide lookup.
        denied = await tools.search_patients(self.db, actor=self.patient_user)
        self.assertFalse(denied.ok)
        self.assertEqual(denied.error.code, "COMMON_FORBIDDEN")
        # A per-account deny override wins over the role default.
        self.receptionist.permission_overrides = {"patient:search": "deny"}
        overridden = await tools.search_patients(
            self.db, actor=self.receptionist
        )
        self.assertFalse(overridden.ok)
        self.assertEqual(overridden.error.code, "COMMON_FORBIDDEN")

    # ------------------------------------------------------------------
    # get_patient_summary
    # ------------------------------------------------------------------

    async def test_patient_summary_counts_and_next_visit(self):
        await self._book(
            self.patient, self.doctor, datetime(2026, 10, 10, 9, 0)
        )
        await self._book(
            self.patient, self.doctor, datetime(2026, 10, 1, 10, 0)
        )
        result = await tools.get_patient_summary(
            self.db, self.patient.id, actor=self.receptionist
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.data.upcoming_count, 1)
        self.assertIsNotNone(result.data.next_appointment)
        self.assertEqual(result.data.record_status, "complete")
        self.assertTrue(result.data.is_account_holder)
        self.assertTrue(result.data.national_id_masked.startswith("***"))
        self.assertEqual(len(result.data.recent_appointments), 1)

    async def test_patient_summary_denied_for_patient_role(self):
        result = await tools.get_patient_summary(
            self.db, self.patient.id, actor=self.patient_user
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "COMMON_FORBIDDEN")

    async def test_patient_summary_unknown_patient(self):
        result = await tools.get_patient_summary(
            self.db, 99999, actor=self.admin
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "PATIENT_NOT_FOUND")

    # ------------------------------------------------------------------
    # get_doctor_schedules
    # ------------------------------------------------------------------

    async def test_schedules_visible_to_every_role_including_patients(self):
        result = await tools.get_doctor_schedules(
            self.db, actor=self.patient_user
        )
        self.assertTrue(result.ok)
        weekdays = {item.weekday for item in result.data.schedules}
        self.assertIn("پنجشنبه", weekdays)
        self.assertIn("جمعه", weekdays)
        for actor in (self.receptionist, self.doctor_user, self.admin):
            staff_result = await tools.get_doctor_schedules(
                self.db, actor=actor
            )
            self.assertTrue(staff_result.ok)

    async def test_schedules_filtered_by_doctor_and_not_found(self):
        result = await tools.get_doctor_schedules(
            self.db, self.doctor.id, actor=self.patient_user
        )
        self.assertTrue(result.ok)
        self.assertTrue(
            all(item.doctor_id == self.doctor.id for item in result.data.schedules)
        )
        empty_doctor = Doctor(
            full_name="دکتر بی‌برنامه",
            specialty="عمومی",
            phone="09930000009",
            is_active=True,
        )
        self.db.add(empty_doctor)
        await self.db.flush()
        missing = await tools.get_doctor_schedules(
            self.db, empty_doctor.id, actor=self.receptionist
        )
        self.assertFalse(missing.ok)
        self.assertEqual(missing.error.code, "DOCTOR_SCHEDULE_NOT_FOUND")

    # ------------------------------------------------------------------
    # get_doctor_day_plan
    # ------------------------------------------------------------------

    async def test_day_plan_for_admin_returns_ids_and_sorted_rows(self):
        early = await self._book(
            self.patient, self.doctor, datetime(2026, 10, 8, 9, 0)
        )
        late = await self._book(
            self.other_patient, self.doctor, datetime(2026, 10, 8, 11, 0)
        )
        cancelled = await self._book(
            self.other_patient,
            self.doctor,
            datetime(2026, 10, 8, 10, 0),
            status="cancelled",
        )
        result = await tools.get_doctor_day_plan(
            self.db, "1405/07/16", self.doctor.id, actor=self.admin
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.data.doctor_id, self.doctor.id)
        self.assertEqual(result.data.weekday, "پنجشنبه")
        # Cancelled rows stay visible with their status; rows are ordered by
        # wall-clock time: early(09:00), cancelled(10:00), late(11:00).
        self.assertEqual(
            [item.appointment_id for item in result.data.appointments],
            [early.id, cancelled.id, late.id],
        )
        self.assertEqual(result.data.appointments[0].patient_name, "مریض نمونه")
        self.assertEqual(result.data.appointments[1].status, "cancelled")
        self.assertIsNotNone(result.data.working_hours)

    async def test_day_plan_doctor_role_pinned_to_own_record(self):
        await self._book(
            self.patient, self.doctor, datetime(2026, 10, 8, 9, 0)
        )
        await self._book(
            self.other_patient, self.other_doctor, datetime(2026, 10, 8, 9, 30)
        )
        # A doctor account naming another doctor is rejected outright, in
        # line with the appointments listing scope contract.
        foreign = await tools.get_doctor_day_plan(
            self.db, "1405/07/16", self.other_doctor.id, actor=self.doctor_user
        )
        self.assertFalse(foreign.ok)
        self.assertEqual(foreign.error.code, "COMMON_FORBIDDEN")
        # Without a doctor choice the plan resolves to the linked record.
        result = await tools.get_doctor_day_plan(
            self.db, "1405/07/16", None, actor=self.doctor_user
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.data.doctor_id, self.doctor.id)
        self.assertEqual(len(result.data.appointments), 1)
        self.assertEqual(result.data.appointments[0].patient_name, "مریض نمونه")

    async def test_day_plan_rejections(self):
        # Patient role is always forbidden.
        patient_call = await tools.get_doctor_day_plan(
            self.db, "1405/07/16", self.doctor.id, actor=self.patient_user
        )
        self.assertFalse(patient_call.ok)
        self.assertEqual(patient_call.error.code, "COMMON_FORBIDDEN")
        # Admin must choose a doctor for a day plan.
        ambiguous = await tools.get_doctor_day_plan(
            self.db, "1405/07/16", None, actor=self.admin
        )
        self.assertFalse(ambiguous.ok)
        self.assertEqual(ambiguous.error.code, "COMMON_VALIDATION_ERROR")
        # A doctor account without a linked doctor record fails closed.
        unlinked = _user("doctor", "09930000010")
        self.db.add(unlinked)
        await self.db.flush()
        result = await tools.get_doctor_day_plan(
            self.db, "1405/07/16", None, actor=unlinked
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "DOCTOR_ACCOUNT_NOT_LINKED")
        # Non-Jalali dates are rejected with the catalogued error.
        bad_date = await tools.get_doctor_day_plan(
            self.db, "2026/10/08", self.doctor.id, actor=self.admin
        )
        self.assertFalse(bad_date.ok)
        self.assertEqual(bad_date.error.code, "APPOINTMENT_INVALID_DATE")

    # ------------------------------------------------------------------
    # get_user_reports_summary
    # ------------------------------------------------------------------

    async def test_user_reports_summary_admin_only(self):
        self.db.add_all(
            [
                FeedbackReport(
                    category="error",
                    message="خطای نمایش تاریخ در صفحه نوبت‌ها",
                    status="new",
                    user_id=self.patient_user.id,
                ),
                FeedbackReport(
                    category="suggestion",
                    message="پیشنهاد یادآوری پیامکی نوبت",
                    status="received",
                ),
            ]
        )
        await self.db.flush()
        result = await tools.get_user_reports_summary(self.db, actor=self.admin)
        self.assertTrue(result.ok)
        self.assertEqual(result.data.total, 2)
        self.assertEqual(result.data.by_category, {"error": 1, "suggestion": 1})
        self.assertEqual(result.data.recent[0].category, "suggestion")
        for actor in (
            self.receptionist,
            self.doctor_user,
            self.patient_user,
        ):
            denied = await tools.get_user_reports_summary(self.db, actor=actor)
            self.assertFalse(denied.ok)
            self.assertEqual(denied.error.code, "COMMON_FORBIDDEN")

    # ------------------------------------------------------------------
    # registry / action-mapping consistency
    # ------------------------------------------------------------------

    def test_every_registry_tool_has_an_action_mapping(self):
        self.assertEqual(set(_TOOL_ACTIONS), set(TOOL_REGISTRY))
        for name, action in _TOOL_ACTIONS.items():
            matrix = effective_permissions(User(role="admin", is_active=True))
            mapped = {row["action"] for row in matrix}
            self.assertIn(
                action,
                mapped,
                f"{name} maps to unknown action {action}",
            )

    def test_new_tools_are_read_only(self):
        for name in (
            "search_patients",
            "get_patient_summary",
            "get_doctor_schedules",
            "get_doctor_day_plan",
            "get_user_reports_summary",
        ):
            self.assertEqual(TOOL_REGISTRY[name].operation, "read")


if __name__ == "__main__":
    unittest.main()
