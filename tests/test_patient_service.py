import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.errors import AppError
from app.models.base import Base
from app.models.patient import Patient
from app.services import patient_service


class PatientServiceTests(unittest.IsolatedAsyncioTestCase):
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

    async def _create_sample_patient(self) -> Patient:
        async with self.session_factory() as db:
            return await patient_service.create_patient(
                db=db,
                national_id="0000000000",
                full_name="بیمار نمونهٔ ساختگی",
                phone="09000000000",
            )

    async def test_create_list_and_get_patient(self):
        created = await self._create_sample_patient()

        async with self.session_factory() as db:
            patients = await patient_service.list_patients(db)
            fetched = await patient_service.get_patient(db, created.id)

        self.assertEqual([patient.id for patient in patients], [created.id])
        self.assertEqual(fetched.national_id, "0000000000")
        self.assertEqual(fetched.full_name, "بیمار نمونهٔ ساختگی")

    async def test_duplicate_national_id_raises_catalog_error(self):
        await self._create_sample_patient()

        async with self.session_factory() as db:
            with self.assertRaises(AppError) as raised:
                await patient_service.create_patient(
                    db=db,
                    national_id="0000000000",
                    full_name="بیمار دوم",
                    phone="09000000001",
                )

        self.assertEqual(
            raised.exception.code,
            "PATIENT_DUPLICATE_NATIONAL_ID",
        )

    async def test_missing_patient_errors_for_get_update_and_delete(self):
        async with self.session_factory() as db:
            operations = (
                patient_service.get_patient(db, 999),
                patient_service.update_patient(db, 999, "نمونه", "09000000002"),
                patient_service.delete_patient(db, 999),
            )
            for operation in operations:
                with self.assertRaises(AppError) as raised:
                    await operation
                self.assertEqual(raised.exception.code, "PATIENT_NOT_FOUND")

    async def test_update_changes_name_and_phone_but_preserves_national_id(self):
        created = await self._create_sample_patient()

        async with self.session_factory() as db:
            updated = await patient_service.update_patient(
                db=db,
                patient_id=created.id,
                full_name="نام نمونهٔ جدید",
                phone="09000000003",
            )

        self.assertEqual(updated.full_name, "نام نمونهٔ جدید")
        self.assertEqual(updated.phone, "09000000003")
        self.assertEqual(updated.national_id, "0000000000")

    async def test_delete_returns_id_and_removes_patient(self):
        created = await self._create_sample_patient()

        async with self.session_factory() as db:
            deleted_id = await patient_service.delete_patient(db, created.id)

        self.assertEqual(deleted_id, created.id)
        async with self.session_factory() as db:
            with self.assertRaises(AppError) as raised:
                await patient_service.get_patient(db, created.id)

        self.assertEqual(raised.exception.code, "PATIENT_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
