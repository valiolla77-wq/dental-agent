import unittest
from datetime import date, datetime, time
from unittest.mock import AsyncMock, patch

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agent_tools.tools import (
    find_available_slots,
    find_doctors_for_service,
    get_patient_appointments,
    search_dental_services,
)
from app.models.appointment import Appointment
from app.models.base import Base
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.doctor_schedule import DoctorSchedule
from app.models.patient import Patient
from app.services import appointment_service
from app.utils.date_utils import gregorian_to_jalali


class AgentToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
        )
        self.target_date = date(2026, 10, 10)
        self.appointment_date = gregorian_to_jalali(
            datetime.combine(self.target_date, time.min)
        )[0]
        async with self.session_factory() as db:
            self.service = DentalService(name="جرم‌گیری نمونه", is_active=True)
            self.other_service = DentalService(name="ترمیم نمونه", is_active=True)
            self.inactive_service = DentalService(
                name="خدمت غیرفعال نمونه",
                is_active=False,
            )
            db.add_all([self.service, self.other_service, self.inactive_service])
            await db.flush()
            self.doctor = Doctor(
                full_name="دکتر فعال نمونه",
                specialty="دندانپزشک عمومی",
                phone="09000000001",
                is_active=True,
                dental_services=[self.service],
            )
            self.unrelated_doctor = Doctor(
                full_name="دکتر نامرتبط نمونه",
                specialty="تخصص نمونه",
                phone="09000000002",
                is_active=True,
                dental_services=[self.other_service],
            )
            self.inactive_doctor = Doctor(
                full_name="دکتر غیرفعال نمونه",
                specialty="تخصص نمونه",
                phone="09000000003",
                is_active=False,
                dental_services=[self.service],
            )
            db.add_all([self.doctor, self.unrelated_doctor, self.inactive_doctor])
            self.patient = Patient(
                national_id="0000000000",
                full_name="بیمار ساختگی ابزار",
                phone="09000000004",
            )
            db.add(self.patient)
            await db.flush()
            db.add(
                DoctorSchedule(
                    doctor_id=self.doctor.id,
                    day_of_week=0,
                    start_time=time(9),
                    end_time=time(13),
                    slot_duration_minutes=30,
                    is_active=True,
                )
            )
            await db.commit()
            for item in (
                self.service,
                self.other_service,
                self.inactive_service,
                self.doctor,
                self.unrelated_doctor,
                self.inactive_doctor,
                self.patient,
            ):
                await db.refresh(item)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_search_returns_active_services_with_minimal_fields(self):
        async with self.session_factory() as db:
            result = await search_dental_services(db, " جرم ")

        self.assertTrue(result.ok)
        self.assertEqual([item.name for item in result.data], ["جرم‌گیری نمونه"])
        self.assertEqual(
            set(result.data[0].model_dump()),
            {"id", "name", "description"},
        )

    async def test_search_without_query_excludes_inactive_services(self):
        async with self.session_factory() as db:
            result = await search_dental_services(db)

        self.assertTrue(result.ok)
        self.assertEqual(
            {item.id for item in result.data},
            {self.service.id, self.other_service.id},
        )
        self.assertNotIn(self.inactive_service.id, {item.id for item in result.data})

    async def test_tool_execution_is_logged_without_logging_search_input(self):
        sensitive_query = "نمونهٔ محرمانهٔ جستجو"
        async with self.session_factory() as db:
            with self.assertLogs("dental_agent.agent_tools", level="INFO") as logs:
                await search_dental_services(db, sensitive_query)

        combined_logs = "\n".join(logs.output)
        self.assertIn("Agent tool started", combined_logs)
        self.assertIn("Agent tool completed", combined_logs)
        self.assertNotIn(sensitive_query, combined_logs)

    async def test_invalid_tool_input_returns_catalogued_validation_error(self):
        async with self.session_factory() as db:
            result = await search_dental_services(db, "x" * 151)

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "COMMON_VALIDATION_ERROR")
        self.assertEqual(result.error.details, {})

    async def test_find_doctors_returns_only_active_providers(self):
        async with self.session_factory() as db:
            result = await find_doctors_for_service(db, self.service.id)

        self.assertTrue(result.ok)
        self.assertEqual([item.id for item in result.data], [self.doctor.id])
        self.assertEqual(
            set(result.data[0].model_dump()),
            {"id", "full_name", "specialty"},
        )

    async def test_inactive_service_has_no_selectable_doctors(self):
        async with self.session_factory() as db:
            result = await find_doctors_for_service(db, self.inactive_service.id)

        self.assertTrue(result.ok)
        self.assertEqual(result.data, [])

    async def test_missing_service_is_reported_with_catalog_code(self):
        async with self.session_factory() as db:
            result = await find_doctors_for_service(db, 999)

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "DENTAL_SERVICE_NOT_FOUND")

    async def test_available_slots_exclude_booked_starts_and_match_service(self):
        async with self.session_factory() as db:
            await appointment_service.create_appointment(
                db,
                self.patient.id,
                self.doctor.id,
                self.service.id,
                self.appointment_date,
                "10:30",
            )
        async with self.session_factory() as db:
            result = await find_available_slots(
                db,
                service_id=self.service.id,
                doctor_id=self.doctor.id,
                appointment_date=self.appointment_date,
            )

        self.assertTrue(result.ok)
        self.assertNotIn("10:30", result.data.available_slots)
        self.assertNotIn("13:00", result.data.available_slots)
        self.assertEqual(result.data.appointment_date, self.appointment_date)

    async def test_cancelled_appointment_does_not_hide_a_slot(self):
        async with self.session_factory() as db:
            appointment = await appointment_service.create_appointment(
                db,
                self.patient.id,
                self.doctor.id,
                self.service.id,
                self.appointment_date,
                "11:00",
            )
            appointment.status = "cancelled"
            await db.commit()
        async with self.session_factory() as db:
            result = await find_available_slots(
                db,
                self.service.id,
                self.doctor.id,
                self.appointment_date,
            )

        self.assertIn("11:00", result.data.available_slots)

    async def test_slot_lookup_rejects_doctor_service_mismatch(self):
        async with self.session_factory() as db:
            result = await find_available_slots(
                db,
                self.other_service.id,
                self.doctor.id,
                self.appointment_date,
            )

        self.assertFalse(result.ok)
        self.assertEqual(
            result.error.code,
            "APPOINTMENT_DOCTOR_SERVICE_MISMATCH",
        )

    async def test_slot_lookup_rejects_inactive_service(self):
        async with self.session_factory() as db:
            result = await find_available_slots(
                db,
                self.inactive_service.id,
                self.doctor.id,
                self.appointment_date,
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "APPOINTMENT_SERVICE_INACTIVE")

    async def test_invalid_date_returns_standard_error_code(self):
        async with self.session_factory() as db:
            result = await find_available_slots(
                db,
                self.service.id,
                self.doctor.id,
                "not-a-date",
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "APPOINTMENT_INVALID_DATE")

    async def test_patient_appointments_return_minimal_data_without_reason(self):
        async with self.session_factory() as db:
            appointment = Appointment(
                patient_id=self.patient.id,
                doctor_id=self.doctor.id,
                service_id=self.service.id,
                appointment_time=datetime(2026, 10, 10, 10, 30),
                status="scheduled",
                reason="اطلاعات آزاد حساس نمونه",
            )
            db.add(appointment)
            await db.commit()
        async with self.session_factory() as db:
            result = await get_patient_appointments(db, self.patient.id)

        self.assertTrue(result.ok)
        self.assertEqual(len(result.data), 1)
        self.assertEqual(result.data[0].appointment_date, self.appointment_date)
        self.assertEqual(result.data[0].appointment_time, "10:30")
        self.assertNotIn("reason", result.data[0].model_dump())
        self.assertNotIn("national_id", result.data[0].model_dump())

    async def test_missing_patient_is_reported_with_catalog_code(self):
        async with self.session_factory() as db:
            result = await get_patient_appointments(db, 999)

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "PATIENT_NOT_FOUND")

    async def test_nonpositive_identifier_returns_validation_error(self):
        async with self.session_factory() as db:
            result = await find_doctors_for_service(db, 0)

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "COMMON_VALIDATION_ERROR")

    async def test_database_exception_returns_generic_catalog_error(self):
        async with self.session_factory() as db:
            with patch(
                "app.agent_tools.tools.dental_service_service.search_dental_services",
                new=AsyncMock(side_effect=SQLAlchemyError("database secret")),
            ):
                with self.assertLogs(
                    "dental_agent.agent_tools",
                    level="ERROR",
                ):
                    result = await search_dental_services(db)

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "DATABASE_ERROR")
        self.assertNotIn("database secret", result.error.model_dump_json())

    async def test_unexpected_exception_returns_generic_catalog_error(self):
        async with self.session_factory() as db:
            with patch(
                "app.agent_tools.tools.dental_service_service.search_dental_services",
                new=AsyncMock(side_effect=RuntimeError("internal secret")),
            ):
                with self.assertLogs(
                    "dental_agent.agent_tools",
                    level="ERROR",
                ):
                    result = await search_dental_services(db)

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "INTERNAL_ERROR")
        self.assertNotIn("internal secret", result.error.model_dump_json())


if __name__ == "__main__":
    unittest.main()
