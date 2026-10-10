import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agent_tools.tools import cancel_appointment
from app.errors import ERROR_CATALOG
from app.models.appointment import Appointment
from app.models.base import Base
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.patient import Patient


class CancelAppointmentToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
        )
        async with self.session_factory() as db:
            self.patient = Patient(
                national_id="0000000000",
                full_name="بیمار نمونه لغو",
                phone="09000000001",
            )
            self.doctor = Doctor(
                full_name="دکتر نمونه لغو",
                specialty="تخصص نمونه",
                phone="09000000002",
            )
            self.service = DentalService(name="خدمت نمونه لغو", is_active=True)
            db.add_all([self.patient, self.doctor, self.service])
            await db.flush()
            self.appointment = Appointment(
                patient_id=self.patient.id,
                doctor_id=self.doctor.id,
                service_id=self.service.id,
                appointment_time=datetime(2026, 10, 10, 10, 30),
                status="scheduled",
                reason="متن خصوصی نمونه",
            )
            db.add(self.appointment)
            await db.commit()
            await db.refresh(self.appointment)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_cancel_succeeds_with_minimal_structured_output(self):
        async with self.session_factory() as db:
            result = await cancel_appointment(db, self.appointment.id)

        self.assertTrue(result.ok)
        self.assertEqual(result.data.appointment_id, self.appointment.id)
        self.assertEqual(result.data.status, "cancelled")
        self.assertEqual(
            set(result.data.model_dump()),
            {"appointment_id", "status"},
        )
        self.assertNotIn("reason", result.model_dump_json())
        async with self.session_factory() as db:
            stored = await db.get(Appointment, self.appointment.id)
        self.assertEqual(stored.status, "cancelled")

    async def test_missing_appointment_returns_catalog_error(self):
        async with self.session_factory() as db:
            result = await cancel_appointment(db, 999)

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "APPOINTMENT_NOT_FOUND")
        self.assertEqual(ERROR_CATALOG[result.error.code].status_code, 404)

    async def test_already_cancelled_appointment_returns_catalog_error(self):
        async with self.session_factory() as db:
            stored = await db.get(Appointment, self.appointment.id)
            stored.status = "cancelled"
            await db.commit()
            result = await cancel_appointment(db, self.appointment.id)

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "APPOINTMENT_ALREADY_CANCELLED")
        self.assertEqual(ERROR_CATALOG[result.error.code].status_code, 409)

    async def test_other_appointment_status_is_not_cancellable(self):
        async with self.session_factory() as db:
            stored = await db.get(Appointment, self.appointment.id)
            stored.status = "completed"
            await db.commit()
            result = await cancel_appointment(db, self.appointment.id)

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "APPOINTMENT_NOT_CANCELLABLE")

    async def test_invalid_appointment_id_returns_validation_error(self):
        async with self.session_factory() as db:
            result = await cancel_appointment(db, 0)

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "COMMON_VALIDATION_ERROR")

    async def test_tool_delegates_to_service_without_using_database_methods(self):
        fake_db = object()
        appointment = Appointment(
            id=123,
            patient_id=1,
            doctor_id=1,
            service_id=1,
            appointment_time=datetime(2026, 10, 10, 10, 30),
            status="cancelled",
        )
        service_call = AsyncMock(return_value=appointment)
        with patch(
            "app.agent_tools.tools.appointment_service.cancel_appointment",
            new=service_call,
        ):
            result = await cancel_appointment(fake_db, 123)

        service_call.assert_awaited_once_with(fake_db, 123)
        self.assertTrue(result.ok)
        self.assertEqual(result.data.appointment_id, 123)

    async def test_database_error_is_generic_and_does_not_log_input(self):
        private_value = "appointment-db-private-value"
        async with self.session_factory() as db:
            with patch(
                "app.agent_tools.tools.appointment_service.cancel_appointment",
                new=AsyncMock(side_effect=SQLAlchemyError(private_value)),
            ):
                with self.assertLogs(
                    "dental_agent.agent_tools",
                    level="ERROR",
                ) as logs:
                    result = await cancel_appointment(db, self.appointment.id)

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "DATABASE_ERROR")
        self.assertNotIn(private_value, result.model_dump_json())
        self.assertNotIn(private_value, "\n".join(logs.output))

    async def test_unexpected_error_is_generic_and_does_not_log_input(self):
        private_value = "appointment-internal-private-value"
        async with self.session_factory() as db:
            with patch(
                "app.agent_tools.tools.appointment_service.cancel_appointment",
                new=AsyncMock(side_effect=RuntimeError(private_value)),
            ):
                with self.assertLogs(
                    "dental_agent.agent_tools",
                    level="ERROR",
                ) as logs:
                    result = await cancel_appointment(db, self.appointment.id)

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "INTERNAL_ERROR")
        self.assertNotIn(private_value, result.model_dump_json())
        self.assertNotIn(private_value, "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
