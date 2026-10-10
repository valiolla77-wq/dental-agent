import unittest
from datetime import datetime

from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.errors import AppError
from app.models.appointment import Appointment
from app.models.base import Base
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.doctor_dental_service import doctor_dental_services
from app.models.patient import Patient
from app.services import dental_service_service, doctor_service


class DentalServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
        )

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def _create_service(self, name="خدمت نمونه", description="شرح نمونه"):
        async with self.session_factory() as db:
            return await dental_service_service.create_dental_service(
                db,
                name,
                description,
            )

    async def test_create_list_and_get_services(self):
        service = await self._create_service()
        async with self.session_factory() as db:
            services = await dental_service_service.list_dental_services(db)
            loaded = await dental_service_service.get_dental_service(db, service.id)

        self.assertEqual([item.id for item in services], [service.id])
        self.assertEqual(loaded.name, "خدمت نمونه")
        self.assertEqual(loaded.description, "شرح نمونه")
        self.assertTrue(loaded.is_active)

    async def test_service_list_defaults_to_active_only(self):
        active = await self._create_service("خدمت فعال")
        inactive = await self._create_service("خدمت غیرفعال")
        async with self.session_factory() as db:
            stored_inactive = await db.get(DentalService, inactive.id)
            stored_inactive.is_active = False
            await db.commit()
            active_services = await dental_service_service.list_dental_services(db)
            all_services = await dental_service_service.list_dental_services(
                db,
                active_only=False,
            )

        self.assertEqual([service.id for service in active_services], [active.id])
        self.assertEqual(
            {service.id for service in all_services},
            {active.id, inactive.id},
        )

    async def test_update_service_can_deactivate_it(self):
        service = await self._create_service()
        async with self.session_factory() as db:
            updated = await dental_service_service.update_dental_service(
                db,
                service.id,
                "نام جدید",
                None,
                False,
            )
        self.assertEqual(updated.name, "نام جدید")
        self.assertIsNone(updated.description)
        self.assertFalse(updated.is_active)

    async def test_missing_service_raises_catalog_error(self):
        async with self.session_factory() as db:
            with self.assertRaises(AppError) as raised:
                await dental_service_service.get_dental_service(db, 999)
        self.assertEqual(raised.exception.code, "DENTAL_SERVICE_NOT_FOUND")

    async def test_duplicate_doctor_service_ids_create_one_relationship(self):
        service = await self._create_service()
        async with self.session_factory() as db:
            doctor = await doctor_service.create_doctor(
                db,
                full_name="دکتر نمونهٔ ساختگی",
                specialty="تخصص نمونه",
                phone="09000000000",
                service_ids=[service.id, service.id],
            )
            relations = await db.execute(
                select(doctor_dental_services).where(
                    doctor_dental_services.c.doctor_id == doctor.id
                )
            )
            relation_rows = relations.fetchall()

        self.assertEqual(len(relation_rows), 1)
        self.assertEqual(relation_rows[0].dental_service_id, service.id)

    async def test_doctor_can_replace_services_during_update(self):
        first = await self._create_service("خدمت اولیه")
        second = await self._create_service("خدمت جایگزین")
        async with self.session_factory() as db:
            doctor = await doctor_service.create_doctor(
                db,
                "دکتر نمونهٔ ساختگی",
                "تخصص نمونه",
                "09000000000",
                [first.id],
            )
            updated = await doctor_service.update_doctor(
                db,
                doctor.id,
                "دکتر ویرایش‌شدهٔ نمونه",
                "تخصص جدید",
                "09000000001",
                True,
                [second.id],
            )
            linked_services = await dental_service_service.get_doctor_services(
                db,
                doctor.id,
            )

        self.assertEqual(updated.full_name, "دکتر ویرایش‌شدهٔ نمونه")
        self.assertEqual([service.id for service in linked_services], [second.id])

    async def test_association_table_rejects_duplicate_pair(self):
        service = await self._create_service()
        async with self.session_factory() as db:
            doctor = await doctor_service.create_doctor(
                db,
                "دکتر نمونهٔ ساختگی",
                "تخصص نمونه",
                "09000000000",
                [service.id],
            )
            with self.assertRaises(IntegrityError):
                await db.execute(
                    insert(doctor_dental_services).values(
                        doctor_id=doctor.id,
                        dental_service_id=service.id,
                    )
                )
                await db.commit()
            await db.rollback()

    async def test_doctor_services_and_active_service_doctors(self):
        first = await self._create_service("خدمت یک")
        second = await self._create_service("خدمت دو")
        async with self.session_factory() as db:
            active_doctor = await doctor_service.create_doctor(
                db,
                "دکتر فعال نمونه",
                "تخصص نمونه",
                "09000000001",
                [first.id, second.id],
            )
            inactive_doctor = await doctor_service.create_doctor(
                db,
                "دکتر غیرفعال نمونه",
                "تخصص نمونه",
                "09000000002",
                [first.id],
            )
            inactive_doctor.is_active = False
            await db.commit()

            linked_services = await dental_service_service.get_doctor_services(
                db,
                active_doctor.id,
            )
            linked_doctors = await dental_service_service.get_service_doctors(
                db,
                first.id,
            )

        self.assertEqual({item.id for item in linked_services}, {first.id, second.id})
        self.assertEqual([doctor.id for doctor in linked_doctors], [active_doctor.id])

    async def test_missing_doctor_services_lookup_raises_catalog_error(self):
        async with self.session_factory() as db:
            with self.assertRaises(AppError) as raised:
                await dental_service_service.get_doctor_services(db, 999)
        self.assertEqual(raised.exception.code, "DOCTOR_NOT_FOUND")

    async def test_inactive_service_has_no_selectable_doctors(self):
        service = await self._create_service()
        async with self.session_factory() as db:
            doctor = await doctor_service.create_doctor(
                db,
                "دکتر نمونهٔ ساختگی",
                "تخصص نمونه",
                "09000000000",
                [service.id],
            )
            stored_service = await db.get(DentalService, service.id)
            stored_service.is_active = False
            await db.commit()
            doctors = await dental_service_service.get_service_doctors(
                db,
                service.id,
            )
        self.assertIsNotNone(doctor.id)
        self.assertEqual(doctors, [])

    async def test_delete_service_removes_it_when_not_used_by_appointment(self):
        service = await self._create_service()
        async with self.session_factory() as db:
            doctor = await doctor_service.create_doctor(
                db,
                "دکتر نمونهٔ ساختگی",
                "تخصص نمونه",
                "09000000000",
                [service.id],
            )
            deleted_id = await dental_service_service.delete_dental_service(
                db,
                service.id,
            )
            loaded = await db.get(DentalService, service.id)
            remaining_links = await db.execute(
                select(doctor_dental_services).where(
                    doctor_dental_services.c.doctor_id == doctor.id
                )
            )
        self.assertEqual(deleted_id, service.id)
        self.assertIsNone(loaded)
        self.assertEqual(remaining_links.fetchall(), [])

    async def test_service_used_by_appointment_cannot_be_deleted(self):
        service = await self._create_service()
        async with self.session_factory() as db:
            patient = Patient(
                national_id="0000000000",
                full_name="بیمار نمونهٔ ساختگی",
                phone="09000000000",
            )
            doctor = Doctor(
                full_name="دکتر نمونهٔ ساختگی",
                specialty="تخصص نمونه",
                phone="09000000001",
            )
            db.add_all([patient, doctor])
            await db.commit()
            appointment = Appointment(
                patient_id=patient.id,
                doctor_id=doctor.id,
                service_id=service.id,
                appointment_time=datetime(2026, 10, 10, 9),
                status="scheduled",
            )
            db.add(appointment)
            await db.commit()
            with self.assertRaises(AppError) as raised:
                await dental_service_service.delete_dental_service(db, service.id)
        self.assertEqual(raised.exception.code, "DENTAL_SERVICE_IN_USE")


if __name__ == "__main__":
    unittest.main()
