"""Reception day flow and expanded clinical record endpoints.

Covers the front-desk journey (check-in → start → complete / no-show) and the
new prescription + treatment-plan surfaces that ride on the clinical record.
"""

import asyncio
import os
import unittest
from datetime import datetime, time
from zoneinfo import ZoneInfo

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only-32-chars-long"
os.environ["JWT_ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"
os.environ["CONFIRMATION_HMAC_SECRET"] = "test-confirmation-hmac-secret-32-chars-long"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from app.auth.security import create_access_token, hash_password  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.appointment import Appointment  # noqa: E402
from app.models.audit_log import AuditLog  # noqa: E402
from app.models.clinical_entry import ClinicalEntry  # noqa: E402
from app.models.dental_service import DentalService  # noqa: E402
from app.models.doctor import Doctor  # noqa: E402
from app.models.patient import Patient  # noqa: E402
from app.models.prescription import Prescription  # noqa: E402
from app.models.tooth_status import ToothStatus  # noqa: E402
from app.models.treatment_plan import TreatmentPlanItem  # noqa: E402
from app.models.user import User  # noqa: E402
from app.utils.date_utils import gregorian_to_jalali  # noqa: E402

PHONE_BASE = "09360007"
DOCTOR_PHONE = PHONE_BASE + "001"
DOCTOR_USER_PHONE = PHONE_BASE + "002"
PATIENT_PHONE = PHONE_BASE + "003"
PATIENT_USER_PHONE = PHONE_BASE + "004"
RECEPTIONIST_PHONE = PHONE_BASE + "005"
ADMIN_PHONE = PHONE_BASE + "006"
PATIENT_NATIONAL_ID = "9400000071"
SERVICE_NAME = "خدمت تست جریان روز"
DOCTOR2_PHONE = PHONE_BASE + "007"


def _run(coro):
    return asyncio.run(coro)


def _clinic_today():
    return datetime.now(ZoneInfo("Asia/Tehran")).date()


def _slot(clock: str) -> datetime:
    hour, minute = (int(part) for part in clock.split(":"))
    return datetime.combine(_clinic_today(), time(hour, minute))


class ReceptionFlowTests(unittest.TestCase):
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
            service = DentalService(name=SERVICE_NAME, is_active=True)
            db.add(service)
            await db.flush()

            doctor_user = User(
                full_name="دکتر جریان روز",
                phone=DOCTOR_USER_PHONE,
                password_hash=hash_password("doctor-pass-123"),
                role="doctor",
                is_active=True,
            )
            patient_user = User(
                full_name="بیمار جریان روز",
                phone=PATIENT_USER_PHONE,
                password_hash=hash_password("patient-pass-123"),
                role="patient",
                is_active=True,
            )
            receptionist = User(
                full_name="پذیرش جریان روز",
                phone=RECEPTIONIST_PHONE,
                password_hash=hash_password("reception-pass-123"),
                role="receptionist",
                is_active=True,
            )
            admin = User(
                full_name="مدیر جریان روز",
                phone=ADMIN_PHONE,
                password_hash=hash_password("admin-pass-123"),
                role="admin",
                is_active=True,
            )
            db.add_all([doctor_user, patient_user, receptionist, admin])
            await db.flush()

            doctor = Doctor(
                full_name="دکتر جریان روز",
                specialty="تخصص جریان روز",
                phone=DOCTOR_PHONE,
                is_active=True,
                user_id=doctor_user.id,
            )
            db.add(doctor)
            await db.flush()

            patient = Patient(
                national_id=PATIENT_NATIONAL_ID,
                full_name="بیمار جریان روز",
                phone=PATIENT_PHONE,
                user_id=patient_user.id,
                is_account_holder=True,
            )
            db.add(patient)
            await db.flush()

            # Three appointments today: a booked one, an already-arrived one
            # and one that will be marked no-show.
            booked = Appointment(
                patient_id=patient.id,
                doctor_id=doctor.id,
                service_id=service.id,
                appointment_time=_slot("09:00"),
                status="scheduled",
                reason="تست پذیرش",
            )
            waiting = Appointment(
                patient_id=patient.id,
                doctor_id=doctor.id,
                service_id=service.id,
                appointment_time=_slot("10:00"),
                status="scheduled",
                reason="تست صف",
                checked_in_at=_slot("09:55"),
                queue_number=1,
            )
            absent = Appointment(
                patient_id=patient.id,
                doctor_id=doctor.id,
                service_id=service.id,
                appointment_time=_slot("11:00"),
                status="scheduled",
                reason="تست عدم مراجعه",
            )
            db.add_all([booked, waiting, absent])
            await db.commit()
            return {
                "admin_user_id": admin.id,
                "doctor_user_id": doctor_user.id,
                "patient_user_id": patient_user.id,
                "receptionist_user_id": receptionist.id,
                "doctor_id": doctor.id,
                "patient_id": patient.id,
                "booked_id": booked.id,
                "waiting_id": waiting.id,
                "absent_id": absent.id,
            }

    async def _cleanup(self):
        async with SessionLocal() as db:
            patient_ids = (
                await db.execute(
                    select(Patient.id).where(Patient.phone == PATIENT_PHONE)
                )
            ).scalars().all()
            user_ids = (
                await db.execute(
                    select(User.id).where(
                        User.phone.in_(
                            [
                                DOCTOR_USER_PHONE,
                                PATIENT_USER_PHONE,
                                RECEPTIONIST_PHONE,
                                ADMIN_PHONE,
                            ]
                        )
                    )
                )
            ).scalars().all()
            if patient_ids:
                await db.execute(
                    delete(Prescription).where(
                        Prescription.patient_id.in_(patient_ids)
                    )
                )
                await db.execute(
                    delete(TreatmentPlanItem).where(
                        TreatmentPlanItem.patient_id.in_(patient_ids)
                    )
                )
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
                    delete(Appointment).where(
                        Appointment.patient_id.in_(patient_ids)
                    )
                )
                await db.execute(
                    delete(Patient).where(Patient.id.in_(patient_ids))
                )
            if user_ids:
                await db.execute(delete(Doctor).where(Doctor.user_id.in_(user_ids)))
                await db.execute(delete(User).where(User.id.in_(user_ids)))
            await db.execute(delete(Doctor).where(Doctor.phone == DOCTOR2_PHONE))
            await db.execute(
                delete(AuditLog).where(
                    AuditLog.action.in_(
                        [
                            "clinical.prescription_create",
                            "clinical.plan_item_create",
                            "clinical.plan_item_update",
                        ]
                    )
                )
            )
            await db.execute(delete(DentalService).where(DentalService.name == SERVICE_NAME))
            await db.commit()

    def _auth(self, role):
        token = create_access_token(subject=str(self.ids[f"{role}_user_id"]))
        return {"Authorization": f"Bearer {token}"}

    def _today_jalali(self):
        return gregorian_to_jalali(datetime.combine(_clinic_today(), time(9)))[0]

    def test_day_worklist_is_time_ordered(self):
        response = self.client.get(
            "/appointments/day",
            params={"appointment_date": self._today_jalali()},
            headers=self._auth("receptionist"),
        )
        self.assertEqual(response.status_code, 200, response.text)
        rows = response.json()
        mine = [row for row in rows if row["patient_id"] == self.ids["patient_id"]]
        self.assertEqual(len(mine), 3)
        self.assertEqual([row["id"] for row in mine], [
            self.ids["booked_id"],
            self.ids["waiting_id"],
            self.ids["absent_id"],
        ])
        self.assertTrue(isinstance(mine[0]["is_late"], bool))
        self.assertEqual(mine[1]["queue_number"], 1)

    def test_queue_numbers_are_per_doctor(self):
        """Each room counts its own arrivals; a shared counter would make the
        second doctor's first patient show up as number 2."""

        async def create_other_doctor_appointment():
            async with SessionLocal() as db:
                service = await db.scalar(
                    select(DentalService).where(DentalService.name == SERVICE_NAME)
                )
                patient = await db.scalar(
                    select(Patient).where(Patient.phone == PATIENT_PHONE)
                )
                other = Doctor(
                    full_name="دکتر اتاق دوم",
                    specialty="تخصص اتاق دوم",
                    phone=DOCTOR2_PHONE,
                    is_active=True,
                )
                db.add(other)
                await db.flush()
                appointment = Appointment(
                    patient_id=patient.id,
                    doctor_id=other.id,
                    service_id=service.id,
                    appointment_time=_slot("12:30"),
                    status="scheduled",
                    reason="تست صف اتاق دوم",
                )
                db.add(appointment)
                await db.commit()
                return appointment.id

        other_id = _run(create_other_doctor_appointment())
        response = self.client.post(
            f"/appointments/{other_id}/check-in",
            headers=self._auth("receptionist"),
        )
        self.assertEqual(response.status_code, 200, response.text)
        # The fixture's first room already has number 1; the second room is
        # empty, so its first arrival must still be number 1.
        self.assertEqual(response.json()["queue_number"], 1)

    def test_patient_cannot_read_day_worklist(self):
        response = self.client.get(
            "/appointments/day",
            params={"appointment_date": self._today_jalali()},
            headers=self._auth("patient"),
        )
        self.assertEqual(response.status_code, 403)

    def test_check_in_start_and_complete(self):
        check_in = self.client.post(
            f"/appointments/{self.ids['booked_id']}/check-in",
            headers=self._auth("receptionist"),
        )
        self.assertEqual(check_in.status_code, 200, check_in.text)
        body = check_in.json()
        self.assertEqual(body["status"], "scheduled")
        self.assertIsNotNone(body["checked_in_at"])
        self.assertIsNotNone(body["queue_number"])
        self.assertGreaterEqual(body["queue_number"], 2)

        started = self.client.post(
            f"/appointments/{self.ids['booked_id']}/start",
            headers=self._auth("doctor"),
        )
        self.assertEqual(started.status_code, 200, started.text)
        self.assertEqual(started.json()["status"], "in_progress")
        self.assertIsNotNone(started.json()["started_at"])

        completed = self.client.post(
            f"/appointments/{self.ids['booked_id']}/complete",
            headers=self._auth("admin"),
        )
        self.assertEqual(completed.status_code, 200, completed.text)
        self.assertEqual(completed.json()["status"], "completed")
        self.assertIsNotNone(completed.json()["completed_at"])

        # Completing twice is a conflict, not a silent success.
        again = self.client.post(
            f"/appointments/{self.ids['booked_id']}/complete",
            headers=self._auth("admin"),
        )
        self.assertEqual(again.status_code, 409)

    def test_no_show_rejected_for_arrived_patient(self):
        response = self.client.post(
            f"/appointments/{self.ids['waiting_id']}/no-show",
            headers=self._auth("receptionist"),
        )
        self.assertEqual(response.status_code, 409)

        allowed = self.client.post(
            f"/appointments/{self.ids['absent_id']}/no-show",
            headers=self._auth("receptionist"),
        )
        self.assertEqual(allowed.status_code, 200, allowed.text)
        self.assertEqual(allowed.json()["status"], "no_show")

    def test_patient_cannot_change_flow(self):
        response = self.client.post(
            f"/appointments/{self.ids['booked_id']}/check-in",
            headers=self._auth("patient"),
        )
        self.assertEqual(response.status_code, 403)

    def test_prescription_and_plan_items_round_trip(self):
        created_prescription = self.client.post(
            f"/clinical/patients/{self.ids['patient_id']}/prescriptions",
            json={
                "items": [
                    {
                        "name": "آموکسی‌سیلین",
                        "dose": "۵۰۰ میلی‌گرم",
                        "frequency": "هر ۸ ساعت",
                        "duration": "۵ روز",
                    }
                ],
                "notes": "بعد از غذا",
            },
            headers=self._auth("doctor"),
        )
        self.assertEqual(created_prescription.status_code, 201, created_prescription.text)
        prescription = created_prescription.json()
        self.assertEqual(prescription["doctor_id"], self.ids["doctor_id"])
        self.assertEqual(prescription["items"][0]["name"], "آموکسی‌سیلین")

        created_plan = self.client.post(
            f"/clinical/patients/{self.ids['patient_id']}/plan-items",
            json={"title": "ترمیم دندان ۲۶", "tooth_fdi": 26},
            headers=self._auth("doctor"),
        )
        self.assertEqual(created_plan.status_code, 201, created_plan.text)
        plan_item = created_plan.json()
        self.assertEqual(plan_item["status"], "planned")
        self.assertEqual(plan_item["tooth_fdi"], 26)

        moved = self.client.put(
            f"/clinical/patients/{self.ids['patient_id']}/plan-items/{plan_item['id']}",
            json={"status": "completed"},
            headers=self._auth("doctor"),
        )
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertEqual(moved.json()["status"], "completed")

        view = self.client.get(
            f"/clinical/patients/{self.ids['patient_id']}",
            headers=self._auth("receptionist"),
        )
        self.assertEqual(view.status_code, 200, view.text)
        body = view.json()
        self.assertEqual(len(body["prescriptions"]), 1)
        self.assertEqual(len(body["plan_items"]), 1)
        self.assertEqual(body["plan_items"][0]["status"], "completed")

    def test_receptionist_cannot_write_prescriptions(self):
        response = self.client.post(
            f"/clinical/patients/{self.ids['patient_id']}/prescriptions",
            json={"items": [{"name": "استامینوفن"}]},
            headers=self._auth("receptionist"),
        )
        self.assertEqual(response.status_code, 403)

    def test_invalid_prescription_rejected(self):
        response = self.client.post(
            f"/clinical/patients/{self.ids['patient_id']}/prescriptions",
            json={"items": [{"name": "ا"}]},
            headers=self._auth("doctor"),
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
