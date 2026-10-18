"""Unit tests for the centralized authorization policy in app/auth/permissions.py.

Identity always comes from an in-memory User object; no HTTP layer is
involved here, so each case exercises the policy functions directly against
an isolated SQLite session.
"""

import unittest
from datetime import datetime

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.permissions import (
    ROLES,
    actor_role,
    authorize_tool_call,
    ensure_appointment_access,
    ensure_bookable_patient,
    ensure_patient_scope,
    linked_patient_id,
    role_allows,
    require_action,
)
from app.errors import AppError
from app.models.appointment import Appointment
from app.models.base import Base
from app.models.patient import Patient
from app.models.user import User


def _user(session, uid, role, phone):
    user = User(
        id=uid,
        full_name=f"user {uid}",
        phone=phone,
        password_hash="hash",
        role=role,
        is_active=True,
    )
    session.add(user)
    return user


def _patient(session, pid, national_id, phone, user_id=None):
    patient = Patient(
        id=pid,
        national_id=national_id,
        full_name=f"patient {pid}",
        phone=phone,
        user_id=user_id,
    )
    session.add(patient)
    return patient


def _appointment(
    session,
    aid,
    patient_id,
    doctor_id=1,
    service_id=1,
    appointment_time=None,
):
    appointment = Appointment(
        id=aid,
        patient_id=patient_id,
        doctor_id=doctor_id,
        service_id=service_id,
        appointment_time=appointment_time
        or datetime(2026, 10, 10, 10, 0),
        status="scheduled",
    )
    session.add(appointment)
    return appointment


class PermissionMatrixTests(unittest.TestCase):
    def test_known_roles(self):
        self.assertEqual(set(ROLES), {"admin", "receptionist", "doctor", "patient"})

    def test_actor_role_rejects_anonymous_and_inactive(self):
        self.assertIsNone(actor_role(None))
        inactive = User(role="admin", is_active=False)
        self.assertIsNone(actor_role(inactive))

    def test_role_matrix_fail_closed(self):
        admin = User(role="admin", is_active=True)
        receptionist = User(role="receptionist", is_active=True)
        doctor = User(role="doctor", is_active=True)
        patient = User(role="patient", is_active=True)
        unknown = User(role="legacy", is_active=True)

        self.assertTrue(role_allows(admin, "patient:delete"))
        self.assertTrue(role_allows(receptionist, "patient:create"))
        self.assertFalse(role_allows(doctor, "patient:create"))
        self.assertFalse(role_allows(doctor, "appointment:cancel"))
        self.assertTrue(role_allows(doctor, "appointment:read"))
        self.assertTrue(role_allows(patient, "clinic:read"))
        self.assertFalse(role_allows(patient, "patient:read"))
        self.assertFalse(role_allows(unknown, "clinic:read"))
        self.assertFalse(role_allows(None, "clinic:read"))

    def test_require_action_raises_forbidden(self):
        with self.assertRaises(AppError) as caught:
            require_action(User(role="patient"), "patient:delete")
        self.assertEqual(caught.exception.code, "COMMON_FORBIDDEN")
        require_action(User(role="admin", is_active=True), "patient:delete")  # no raise


class PatientScopeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.session = session_factory()
        self.admin = _user(self.session, 1, "admin", "09110000001")
        self.receptionist = _user(self.session, 2, "receptionist", "09110000002")
        self.doctor = _user(self.session, 3, "doctor", "09110000003")
        self.patient_a_user = _user(self.session, 4, "patient", "09110000004")
        self.patient_b_user = _user(self.session, 5, "patient", "09110000005")
        self.unlinked_user = _user(self.session, 6, "patient", "09110000006")
        self.patient_a = _patient(self.session, 10, "1000000000", "09110000004", user_id=4)
        self.patient_b = _patient(self.session, 11, "1100000000", "09110000005", user_id=5)
        self.orphan_patient = _patient(self.session, 12, "1200000000", "09110000007", user_id=None)
        await self.session.commit()

    async def asyncTearDown(self):
        await self.session.close()
        await self.engine.dispose()

    async def test_staff_can_read_any_patient(self):
        for actor in (self.admin, self.receptionist, self.doctor):
            resolved = await ensure_patient_scope(
                self.session, actor, self.patient_a.id, "patient:read"
            )
            self.assertEqual(resolved, self.patient_a.id)

    async def test_patient_can_only_read_own_record(self):
        resolved = await ensure_patient_scope(
            self.session, self.patient_a_user, self.patient_a.id, "patient:read"
        )
        self.assertEqual(resolved, self.patient_a.id)
        with self.assertRaises(AppError) as caught:
            await ensure_patient_scope(
                self.session, self.patient_a_user, self.patient_b.id, "patient:read"
            )
        self.assertEqual(caught.exception.code, "COMMON_FORBIDDEN")
        with self.assertRaises(AppError) as caught:
            await ensure_patient_scope(
                self.session, self.unlinked_user, self.orphan_patient.id, "patient:read"
            )
        self.assertEqual(caught.exception.code, "PATIENT_ACCOUNT_NOT_LINKED")

    async def test_anonymous_is_rejected(self):
        with self.assertRaises(AppError) as caught:
            await ensure_patient_scope(self.session, None, 1, "patient:read")
        self.assertEqual(caught.exception.code, "COMMON_UNAUTHORIZED")

    async def test_linked_patient_id(self):
        self.assertEqual(await linked_patient_id(self.session, self.patient_a_user), 10)
        self.assertEqual(await linked_patient_id(self.session, self.admin), None)
        self.assertEqual(await linked_patient_id(self.session, self.unlinked_user), None)

    async def test_update_scope_matches_read_scope(self):
        resolved = await ensure_patient_scope(
            self.session, self.patient_b_user, self.patient_b.id, "patient:update"
        )
        self.assertEqual(resolved, self.patient_b.id)
        with self.assertRaises(AppError):
            await ensure_patient_scope(
                self.session, self.patient_a_user, self.patient_b.id, "patient:update"
            )


class AppointmentAccessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.session = session_factory()
        self.admin = _user(self.session, 1, "admin", "09110000001")
        self.patient_owner = _user(self.session, 2, "patient", "09110000002")
        self.patient_other = _user(self.session, 3, "patient", "09110000003")
        self.patient_own_record = _patient(
            self.session, 20, "2000000000", "09110000002", user_id=2
        )
        self.patient_other_record = _patient(
            self.session, 21, "2100000000", "09110000003", user_id=3
        )
        self.own_appt = _appointment(self.session, 100, 20)
        self.other_appt = _appointment(
            self.session,
            101,
            21,
            appointment_time=datetime(2026, 10, 10, 11, 0),
        )
        await self.session.commit()

    async def asyncTearDown(self):
        await self.session.close()
        await self.engine.dispose()

    async def test_staff_accesses_any_appointment(self):
        for actor in (self.admin,):
            appt = await ensure_appointment_access(
                self.session, actor, self.other_appt.id, "appointment:cancel"
            )
            self.assertEqual(appt.id, self.other_appt.id)

    async def test_patient_accesses_only_own_appointment(self):
        appt = await ensure_appointment_access(
            self.session, self.patient_owner, self.own_appt.id, "appointment:cancel"
        )
        self.assertEqual(appt.id, self.own_appt.id)
        with self.assertRaises(AppError) as caught:
            await ensure_appointment_access(
                self.session, self.patient_owner, self.other_appt.id, "appointment:read"
            )
        self.assertEqual(caught.exception.code, "COMMON_FORBIDDEN")

    async def test_missing_appointment(self):
        with self.assertRaises(AppError) as caught:
            await ensure_appointment_access(
                self.session, self.admin, 999999, "appointment:read"
            )
        self.assertEqual(caught.exception.code, "APPOINTMENT_NOT_FOUND")


class BookablePatientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.session = session_factory()
        self.admin = _user(self.session, 1, "admin", "09110000001")
        self.receptionist = _user(self.session, 2, "receptionist", "09110000002")
        self.patient_user = _user(self.session, 3, "patient", "09110000003")
        self.existing = _patient(
            self.session, 30, "3000000000", "09110000003", user_id=3
        )
        self.other = _patient(self.session, 31, "3100000000", "09110000004", user_id=None)
        await self.session.commit()

    async def asyncTearDown(self):
        await self.session.close()
        await self.engine.dispose()

    async def test_staff_uses_explicit_id_or_national_id(self):
        resolved = await ensure_bookable_patient(
            self.session, self.admin, self.other.id, None
        )
        self.assertEqual(resolved, self.other.id)
        resolved = await ensure_bookable_patient(
            self.session, self.receptionist, None, "3000000000"
        )
        self.assertEqual(resolved, self.existing.id)

    async def test_staff_must_supply_identifier(self):
        with self.assertRaises(AppError) as caught:
            await ensure_bookable_patient(self.session, self.admin, None, None)
        self.assertEqual(caught.exception.code, "COMMON_VALIDATION_ERROR")

    async def test_patient_books_only_own_linked_record(self):
        resolved = await ensure_bookable_patient(
            self.session, self.patient_user, self.existing.id, None
        )
        self.assertEqual(resolved, self.existing.id)
        resolved = await ensure_bookable_patient(
            self.session, self.patient_user, None, "3000000000"
        )
        self.assertEqual(resolved, self.existing.id)
        with self.assertRaises(AppError) as caught:
            await ensure_bookable_patient(
                self.session, self.patient_user, self.other.id, None
            )
        self.assertEqual(caught.exception.code, "COMMON_FORBIDDEN")
        unlinked = _user(self.session, 4, "patient", "09110000009")
        with self.assertRaises(AppError) as caught:
            await ensure_bookable_patient(
                self.session, unlinked, None, None
            )
        self.assertEqual(caught.exception.code, "PATIENT_ACCOUNT_NOT_LINKED")


class ToolAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.session = session_factory()
        self.admin = _user(self.session, 1, "admin", "09110000001")
        self.receptionist = _user(self.session, 2, "receptionist", "09110000002")
        self.doctor = _user(self.session, 3, "doctor", "09110000003")
        self.patient_user = _user(self.session, 4, "patient", "09110000004")
        self.other_user = _user(self.session, 5, "patient", "09110000005")
        self.patient_record = _patient(
            self.session, 40, "4000000000", "09110000004", user_id=4
        )
        self.other_record = _patient(
            self.session, 41, "4100000000", "09110000005", user_id=5
        )
        self.appt = _appointment(self.session, 200, 40)
        await self.session.commit()

    async def asyncTearDown(self):
        await self.session.close()
        await self.engine.dispose()

    async def test_unknown_tool_and_bad_arguments(self):
        with self.assertRaises(AppError) as caught:
            await authorize_tool_call(
                self.session, self.admin, "execute_sql", {"query": "select 1"}
            )
        self.assertEqual(caught.exception.code, "COMMON_FORBIDDEN")
        with self.assertRaises(AppError) as caught:
            await authorize_tool_call(
                self.session, self.admin, "search_dental_services", "not-a-dict"
            )
        self.assertEqual(caught.exception.code, "COMMON_FORBIDDEN")

    async def test_clinic_read_is_open_to_all_authenticated_roles(self):
        for actor in (self.admin, self.receptionist, self.doctor, self.patient_user):
            await authorize_tool_call(
                self.session, actor, "search_dental_services", {}
            )
        with self.assertRaises(AppError) as caught:
            await authorize_tool_call(self.session, None, "search_dental_services", {})

    async def test_receptionist_can_book_for_any_patient(self):
        await authorize_tool_call(
            self.session,
            self.receptionist,
            "book_appointment",
            {"patient_id": self.other_record.id, "doctor_id": 1, "service_id": 1},
        )

    async def test_patient_books_only_own_record(self):
        await authorize_tool_call(
            self.session,
            self.patient_user,
            "book_appointment",
            {"patient_id": self.patient_record.id},
        )
        with self.assertRaises(AppError) as caught:
            await authorize_tool_call(
                self.session,
                self.patient_user,
                "book_appointment",
                {"patient_id": self.other_record.id},
            )
        self.assertEqual(caught.exception.code, "COMMON_FORBIDDEN")

    async def test_patient_reads_own_appointments_only(self):
        await authorize_tool_call(
            self.session,
            self.patient_user,
            "get_patient_appointments",
            {"patient_id": self.patient_record.id},
        )
        with self.assertRaises(AppError) as caught:
            await authorize_tool_call(
                self.session,
                self.patient_user,
                "get_patient_appointments",
                {"patient_id": self.other_record.id},
            )
        self.assertEqual(caught.exception.code, "COMMON_FORBIDDEN")

    async def test_patient_cancel_and_reschedule_require_own_appointment(self):
        await authorize_tool_call(
            self.session,
            self.patient_user,
            "cancel_appointment",
            {"appointment_id": self.appt.id},
        )
        alien = _appointment(
            self.session,
            201,
            41,
            appointment_time=datetime(2026, 10, 10, 11, 0),
        )
        self.session.add(alien)
        await self.session.commit()
        with self.assertRaises(AppError) as caught:
            await authorize_tool_call(
                self.session,
                self.patient_user,
                "cancel_appointment",
                {"appointment_id": alien.id},
            )
        self.assertEqual(caught.exception.code, "COMMON_FORBIDDEN")

    async def test_doctor_cannot_write_appointments(self):
        with self.assertRaises(AppError) as caught:
            await authorize_tool_call(
                self.session,
                self.doctor,
                "book_appointment",
                {"patient_id": self.patient_record.id},
            )
        self.assertEqual(caught.exception.code, "COMMON_FORBIDDEN")


if __name__ == "__main__":
    unittest.main()