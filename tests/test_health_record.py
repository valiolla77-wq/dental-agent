"""Clinical record endpoints: ownership scoping, staff writes, audit trail."""

import asyncio
import os
import unittest

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only-32-chars-long"
os.environ["JWT_ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"
os.environ["CONFIRMATION_HMAC_SECRET"] = "test-confirmation-hmac-secret-32-chars-long"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from app.auth.security import create_access_token, hash_password  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.audit_log import AuditLog  # noqa: E402
from app.models.clinical_entry import ClinicalEntry  # noqa: E402
from app.models.doctor import Doctor  # noqa: E402
from app.models.notification import Notification  # noqa: E402
from app.models.patient import Patient  # noqa: E402
from app.models.tooth_status import ToothStatus  # noqa: E402
from app.models.user import User  # noqa: E402

PHONE_BASE = "09360004"
DOCTOR_PHONE = PHONE_BASE + "001"
PATIENT_PHONE = PHONE_BASE + "002"
OTHER_PATIENT_PHONE = PHONE_BASE + "003"
RECEPTIONIST_PHONE = PHONE_BASE + "004"
ADMIN_PHONE = PHONE_BASE + "005"
OTHER_ADMIN_NOTE = "یادداشت مدیر آزمایشی"


def _run(coro):
    return asyncio.run(coro)


class HealthRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _run(init_db())

    def setUp(self):
        self.client = TestClient(app)
        self.ids = _run(self._seed())

    def tearDown(self):
        _run(self._cleanup())

    async def _seed(self):
        async with SessionLocal() as db:
            admin = User(
                full_name="مدیر پرونده",
                phone=ADMIN_PHONE,
                password_hash=hash_password("admin-pass-123"),
                role="admin",
                is_active=True,
            )
            receptionist = User(
                full_name="پذیرش پرونده",
                phone=RECEPTIONIST_PHONE,
                password_hash=hash_password("reception-pass-123"),
                role="receptionist",
                is_active=True,
            )
            doctor_user = User(
                full_name="دکتر پرونده",
                phone=DOCTOR_PHONE,
                password_hash=hash_password("doctor-pass-123"),
                role="doctor",
                is_active=True,
            )
            patient_user = User(
                full_name="بیمار پرونده",
                phone=PATIENT_PHONE,
                password_hash=hash_password("patient-pass-123"),
                role="patient",
                is_active=True,
            )
            other_user = User(
                full_name="بیمار دیگر پرونده",
                phone=OTHER_PATIENT_PHONE,
                password_hash=hash_password("patient-pass-123"),
                role="patient",
                is_active=True,
            )
            db.add_all(
                [admin, receptionist, doctor_user, patient_user, other_user]
            )
            await db.flush()

            doctor = Doctor(
                full_name="دکتر پرونده",
                specialty="تخصص پرونده",
                phone=DOCTOR_PHONE,
                is_active=True,
                user_id=doctor_user.id,
            )
            db.add(doctor)
            await db.flush()

            patient = Patient(
                national_id="9400000011",
                full_name="بیمار پرونده",
                phone=PATIENT_PHONE,
                user_id=patient_user.id,
                is_account_holder=True,
            )
            other_patient = Patient(
                national_id="9400000012",
                full_name="بیمار دیگر پرونده",
                phone=OTHER_PATIENT_PHONE,
                user_id=other_user.id,
                is_account_holder=True,
            )
            db.add_all([patient, other_patient])
            await db.commit()
            return {
                "admin_user_id": admin.id,
                "receptionist_user_id": receptionist.id,
                "doctor_user_id": doctor_user.id,
                "doctor_id": doctor.id,
                "patient_user_id": patient_user.id,
                "patient_id": patient.id,
                "other_user_id": other_user.id,
                "other_patient_id": other_patient.id,
            }

    async def _cleanup(self):
        async with SessionLocal() as db:
            patient_ids = (
                await db.execute(
                    select(Patient.id).where(
                        Patient.phone.in_([PATIENT_PHONE, OTHER_PATIENT_PHONE])
                    )
                )
            ).scalars().all()
            user_ids = (
                await db.execute(
                    select(User.id).where(
                        User.phone.in_(
                            [
                                DOCTOR_PHONE,
                                PATIENT_PHONE,
                                OTHER_PATIENT_PHONE,
                                RECEPTIONIST_PHONE,
                                ADMIN_PHONE,
                            ]
                        )
                    )
                )
            ).scalars().all()
            if patient_ids:
                await db.execute(
                    delete(ClinicalEntry).where(
                        ClinicalEntry.patient_id.in_(patient_ids)
                    )
                )
                await db.execute(
                    delete(ToothStatus).where(
                        ToothStatus.patient_id.in_(patient_ids)
                    )
                )
                await db.execute(
                    delete(Notification).where(
                        Notification.user_id.in_(user_ids)
                    )
                )
                await db.execute(
                    delete(AuditLog).where(
                        AuditLog.action.in_(
                            ["clinical.entry_create", "clinical.tooth_status"]
                        )
                    )
                )
                await db.execute(
                    delete(Patient).where(Patient.id.in_(patient_ids))
                )
            if user_ids:
                await db.execute(
                    delete(Doctor).where(Doctor.user_id.in_(user_ids))
                )
                await db.execute(delete(User).where(User.id.in_(user_ids)))
            await db.commit()

    def _auth(self, role):
        token = create_access_token(subject=str(self.ids[f"{role}_user_id"]))
        return {"Authorization": f"Bearer {token}"}

    def test_patient_sees_own_record_bundle(self):
        response = self.client.get("/clinical/me", headers=self._auth("patient"))
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body["records"]), 1)
        record = body["records"][0]
        self.assertEqual(record["patient"]["id"], self.ids["patient_id"])
        self.assertEqual(record["entries"], [])
        self.assertEqual(record["teeth"], [])

    def test_staff_cannot_use_patient_self_endpoint(self):
        response = self.client.get("/clinical/me", headers=self._auth("doctor"))
        self.assertEqual(response.status_code, 403)

    def test_doctor_creates_entry_and_patient_sees_it(self):
        created = self.client.post(
            f"/clinical/patients/{self.ids['patient_id']}/entries",
            json={
                "kind": "treatment",
                "title": "پرکردن کامپوزیت",
                "body": "حفر کلاس دو، بی‌حسی موضعی",
                "tooth_fdi": 16,
            },
            headers=self._auth("doctor"),
        )
        self.assertEqual(created.status_code, 201, created.text)
        entry = created.json()
        self.assertEqual(entry["kind"], "treatment")
        self.assertEqual(entry["tooth_fdi"], 16)
        # doctor_id resolved from the linked doctor account
        self.assertEqual(entry["doctor_id"], self.ids["doctor_id"])
        self.assertEqual(entry["doctor_name"], "دکتر پرونده")

        patient_view = self.client.get(
            "/clinical/me", headers=self._auth("patient")
        ).json()
        entries = patient_view["records"][0]["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "پرکردن کامپوزیت")

        # The owning patient account gets an inbox nudge too.
        notifications = self.client.get(
            "/notifications/me", headers=self._auth("patient")
        ).json()
        kinds = [item["kind"] for item in notifications["items"]]
        self.assertIn("clinical_entry", kinds)

    def test_admin_allergy_entry_and_tooth_chart(self):
        allergy = self.client.post(
            f"/clinical/patients/{self.ids['patient_id']}/entries",
            json={"kind": "allergy", "title": "حساسیت به پنی‌سیلین"},
            headers=self._auth("admin"),
        )
        self.assertEqual(allergy.status_code, 201, allergy.text)

        tooth = self.client.put(
            f"/clinical/patients/{self.ids['patient_id']}/teeth/26",
            json={"status": "needs_treatment", "note": "پوسیدگی اولیه"},
            headers=self._auth("admin"),
        )
        self.assertEqual(tooth.status_code, 200, tooth.text)
        self.assertEqual(tooth.json()["status"], "needs_treatment")

        view = self.client.get(
            f"/clinical/patients/{self.ids['patient_id']}",
            headers=self._auth("receptionist"),
        )
        self.assertEqual(view.status_code, 200, view.text)
        body = view.json()
        self.assertEqual(body["entries"][0]["kind"], "allergy")
        self.assertEqual(body["teeth"][0]["tooth_fdi"], 26)

    def test_receptionist_is_read_only(self):
        denied_entry = self.client.post(
            f"/clinical/patients/{self.ids['patient_id']}/entries",
            json={"kind": "note", "title": "تست پذیرش"},
            headers=self._auth("receptionist"),
        )
        self.assertEqual(denied_entry.status_code, 403)

        denied_tooth = self.client.put(
            f"/clinical/patients/{self.ids['patient_id']}/teeth/11",
            json={"status": "treated"},
            headers=self._auth("receptionist"),
        )
        self.assertEqual(denied_tooth.status_code, 403)

    def test_patient_cannot_write_clinical_data(self):
        denied = self.client.post(
            f"/clinical/patients/{self.ids['patient_id']}/entries",
            json={"kind": "note", "title": "تست بیمار"},
            headers=self._auth("patient"),
        )
        self.assertEqual(denied.status_code, 403)

    def test_patient_cannot_read_other_accounts_record(self):
        denied = self.client.get(
            f"/clinical/patients/{self.ids['other_patient_id']}",
            headers=self._auth("patient"),
        )
        self.assertEqual(denied.status_code, 403)

    def test_invalid_tooth_number_rejected(self):
        # 19 passes the 11..48 API bound but is not a valid FDI tooth
        # (quadrant 1 has teeth 1-8), so the service-level check fires.
        response = self.client.post(
            f"/clinical/patients/{self.ids['patient_id']}/entries",
            json={"kind": "treatment", "title": "تست", "tooth_fdi": 19},
            headers=self._auth("doctor"),
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "TOOTH_INVALID")

    def test_invalid_entry_kind_rejected(self):
        response = self.client.post(
            f"/clinical/patients/{self.ids['patient_id']}/entries",
            json={"kind": "surgery", "title": "تست"},
            headers=self._auth("doctor"),
        )
        self.assertEqual(response.status_code, 422)

    def test_invalid_tooth_status_rejected(self):
        # The schema's Literal rejects unknown statuses with a 422 before the
        # service-level TOOTH_STATUS_INVALID guard would fire.
        response = self.client.put(
            f"/clinical/patients/{self.ids['patient_id']}/teeth/11",
            json={"status": "gold"},
            headers=self._auth("doctor"),
        )
        self.assertEqual(response.status_code, 422)

    def test_audit_rows_written_for_clinical_writes(self):
        self.client.post(
            f"/clinical/patients/{self.ids['patient_id']}/entries",
            json={"kind": "note", "title": OTHER_ADMIN_NOTE},
            headers=self._auth("admin"),
        )
        self.client.put(
            f"/clinical/patients/{self.ids['patient_id']}/teeth/36",
            json={"status": "extracted"},
            headers=self._auth("admin"),
        )

        async def _rows():
            async with SessionLocal() as db:
                result = await db.execute(
                    select(AuditLog.action).where(
                        AuditLog.action.in_(
                            ["clinical.entry_create", "clinical.tooth_status"]
                        ),
                        AuditLog.target_user_id.is_(None),
                    )
                )
                return [row[0] for row in result.all()]

        actions = _run(_rows())
        self.assertIn("clinical.entry_create", actions)
        self.assertIn("clinical.tooth_status", actions)


if __name__ == "__main__":
    unittest.main()
