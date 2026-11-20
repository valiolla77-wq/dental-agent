"""End-to-end tests for the patient record completeness flow over HTTP.

Covers §4 of the mission: self-service initial record creation (linked
server-side to the authenticated patient account), staff completion of an
incomplete record via the optional ``national_id`` on ``PUT /patients/{id}``,
and the ``record_status`` staff filter. The identity that links a record is
always the authenticated account, never a client-declared id.
"""

import asyncio
import os
import unittest

# Set test environment variables BEFORE importing app modules.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only-32-chars-long"
os.environ["JWT_ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"
os.environ["CONFIRMATION_HMAC_SECRET"] = (
    "test-confirmation-hmac-secret-32-chars-long"
)
os.environ["CONFIRMATION_TTL_SECONDS"] = "300"

from fastapi.testclient import TestClient  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.auth.security import create_access_token, hash_password  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.chat import AgentConversation  # noqa: E402
from app.models.patient import Patient  # noqa: E402
from app.models.user import User  # noqa: E402
from app.routers.agent_chat import get_chat_llm  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _create_user(phone, *, role, full_name="کاربر پرونده آزمایشی"):
    async def _create():
        async with SessionLocal() as db:
            user = User(
                full_name=full_name,
                phone=phone,
                password_hash=hash_password("probe-pass-123"),
                role=role,
                is_active=True,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            return user

    return _run(_create())


def _delete_user_and_record(phone):
    async def _delete():
        async with SessionLocal() as db:
            user = (
                await db.execute(select(User).where(User.phone == phone))
            ).scalar_one_or_none()
            if user is not None:
                patients = (
                    await db.execute(
                        select(Patient).where(Patient.user_id == user.id)
                    )
                ).scalars().all()
                for patient in patients:
                    await db.delete(patient)
                await db.delete(user)
            await db.commit()

    _run(_delete())


def _create_legacy_incomplete_patient(user_id, phone, full_name="ناقص قدیمی"):
    """Seed a legacy row that predates the mandatory national id."""

    async def _create():
        async with SessionLocal() as db:
            patient = Patient(
                national_id=None,
                full_name=full_name,
                phone=phone,
                user_id=user_id,
                is_account_holder=False,
                record_status="incomplete",
            )
            db.add(patient)
            await db.commit()
            await db.refresh(patient)
            return patient.id

    return _run(_create())


def _delete_patient_by_national_id(national_id):
    async def _delete():
        async with SessionLocal() as db:
            patient = (
                await db.execute(
                    select(Patient).where(Patient.national_id == national_id)
                )
            ).scalar_one_or_none()
            if patient is not None:
                await db.delete(patient)
                await db.commit()

    _run(_delete())


def _delete_patients_of_user_id(user_id):
    """Remove chat state owned by a probe user (conversation + messages)."""

    async def _delete():
        async with SessionLocal() as db:
            rows = (
                await db.execute(
                    select(AgentConversation).where(
                        AgentConversation.user_id == user_id
                    )
                )
            ).scalars().all()
            for row in rows:
                await db.delete(row)
            await db.commit()

    _run(_delete())


class FakeChatModel:
    """Minimal ToolCallingChatModel stand-in returning scripted responses."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0
        self.tool_schemas = []

    def bind_tools(self, tool_schemas):
        self.tool_schemas = list(tool_schemas)
        return self

    async def ainvoke(self, _messages):
        self.calls += 1
        return self.responses.pop(0)


def _book_call(*, call_id="call-book-1"):
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "book_appointment",
                "args": {
                    "doctor_id": 1,
                    "service_id": 1,
                    "appointment_date": "1405/08/25",
                    "appointment_time": "10:00",
                },
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )


class PatientRecordFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _run(init_db())

    def setUp(self):
        self.client = TestClient(app)
        self.admin_phone = "09370005001"
        self.patient_phone = "09370005002"
        self.other_phone = "09370005003"
        for phone in (
            self.admin_phone,
            self.patient_phone,
            self.other_phone,
        ):
            _delete_user_and_record(phone)
        self.admin = _create_user(self.admin_phone, role="admin")
        self.patient_user = _create_user(self.patient_phone, role="patient")
        self.admin_token = create_access_token(subject=str(self.admin.id))
        self.patient_token = create_access_token(
            subject=str(self.patient_user.id)
        )
        self.cleanup_national_ids = []
        self.chat_llm_override = False

    def tearDown(self):
        if self.chat_llm_override:
            app.dependency_overrides.pop(get_chat_llm, None)
        _delete_patients_of_user_id(self.patient_user.id)
        if self.admin is not None:
            _delete_patients_of_user_id(self.admin.id)
        for national_id in self.cleanup_national_ids:
            _delete_patient_by_national_id(national_id)
        for phone in (
            self.admin_phone,
            self.patient_phone,
            self.other_phone,
        ):
            _delete_user_and_record(phone)

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    # ---------------------------------------------------------------- post /me

    def test_self_registration_creates_complete_holder_record(self):
        self.cleanup_national_ids.append("1000999911")
        response = self.client.post(
            "/patients/me",
            json={
                "full_name": "سارا احمدی",
                "phone": self.patient_phone,
                "national_id": "1000999911",
                "relation": "self",
            },
            headers=self._auth(self.patient_token),
        )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["record_status"], "complete")
        self.assertEqual(body["national_id"], "1000999911")
        self.assertTrue(body["is_account_holder"])
        self.assertEqual(body["full_name"], "سارا احمدی")
        self.assertEqual(body["phone"], self.patient_phone)

        # The record is visible to the own account, exactly one.
        listing = self.client.get(
            "/patients/", headers=self._auth(self.patient_token)
        )
        self.assertEqual(listing.status_code, 200)
        records = listing.json()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["id"], body["id"])
        self.assertEqual(records[0]["record_status"], "complete")
        self.assertEqual(records[0]["phone"], self.patient_phone)

        # A repeat self registration cannot create a second holder record.
        second = self.client.post(
            "/patients/me",
            json={
                "full_name": "سارا دوباره",
                "phone": self.patient_phone,
                "national_id": "1000999912",
                "relation": "self",
            },
            headers=self._auth(self.patient_token),
        )
        self.assertEqual(second.status_code, 409)
        self.assertEqual(
            second.json()["error"]["code"], "COMMON_CONFLICT"
        )

    def test_account_can_register_and_list_multiple_patients(self):
        self.cleanup_national_ids.extend(["1000999917", "1000999918"])
        holder = self.client.post(
            "/patients/me",
            json={
                "full_name": "صاحب حساب",
                "phone": self.patient_phone,
                "national_id": "1000999917",
                "relation": "self",
            },
            headers=self._auth(self.patient_token),
        )
        self.assertEqual(holder.status_code, 201, holder.text)

        family_phone = "09370005790"
        dependent = self.client.post(
            "/patients/me",
            json={
                "full_name": "عضو خانواده",
                "phone": family_phone,
                "national_id": "1000999918",
                "relation": "other",
            },
            headers=self._auth(self.patient_token),
        )
        self.assertEqual(dependent.status_code, 201, dependent.text)
        self.assertFalse(dependent.json()["is_account_holder"])

        listing = self.client.get(
            "/patients/", headers=self._auth(self.patient_token)
        )
        self.assertEqual(listing.status_code, 200)
        records = listing.json()
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["id"], holder.json()["id"])
        self.assertTrue(records[0]["is_account_holder"])
        self.assertEqual(records[1]["phone"], family_phone)

        me = self.client.get(
            "/auth/me", headers=self._auth(self.patient_token)
        )
        self.assertEqual(me.status_code, 200)
        self.assertEqual(len(me.json()["patients"]), 2)

        # A second patient cannot reuse the same phone number.
        duplicate = self.client.post(
            "/patients/me",
            json={
                "full_name": "تلفن تکراری",
                "phone": family_phone,
                "national_id": "1000999919",
                "relation": "other",
            },
            headers=self._auth(self.patient_token),
        )
        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        self.assertEqual(
            duplicate.json()["error"]["code"], "PATIENT_DUPLICATE_PHONE"
        )

    def test_self_registration_requires_matching_account_phone(self):
        response = self.client.post(
            "/patients/me",
            json={
                "full_name": "بی‌تطبیق",
                "phone": "09370005999",
                "national_id": "1000999913",
                "relation": "self",
            },
            headers=self._auth(self.patient_token),
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(
            response.json()["error"]["code"], "COMMON_VALIDATION_ERROR"
        )

    def test_self_registration_is_patient_role_only(self):
        response = self.client.post(
            "/patients/me",
            json={
                "full_name": "منشی نیستم",
                "phone": self.admin_phone,
                "national_id": "1000999914",
                "relation": "self",
            },
            headers=self._auth(self.admin_token),
        )
        self.assertEqual(response.status_code, 403, response.text)

    def test_self_registration_requires_authentication(self):
        response = self.client.post(
            "/patients/me",
            json={"full_name": "بی‌توکن", "phone": "09370005002"},
        )
        self.assertEqual(response.status_code, 401, response.text)

    # ------------------------------------------------------- adoption by id

    def test_self_registration_adopts_existing_unlinked_record_same_phone(self):
        _delete_patient_by_national_id("1000999901")
        self.cleanup_national_ids.append("1000999901")
        created = self.client.post(
            "/patients/",
            json={
                "national_id": "1000999901",
                "full_name": "بیمار پذيرش",
                "phone": self.patient_phone,
            },
            headers=self._auth(self.admin_token),
        )
        self.assertEqual(created.status_code, 200, created.text)
        clinic_record_id = created.json()["id"]

        response = self.client.post(
            "/patients/me",
            json={
                "full_name": "بیمار پذيرش",
                "phone": self.patient_phone,
                "national_id": "1000999901",
                "relation": "self",
            },
            headers=self._auth(self.patient_token),
        )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        # The existing clinic record is adopted, not duplicated.
        self.assertEqual(body["id"], clinic_record_id)
        self.assertEqual(body["record_status"], "complete")
        self.assertEqual(body["national_id"], "1000999901")
        self.assertEqual(body["phone"], self.patient_phone)

        # The adopted record is now linked exactly once to this account.
        async def _check():
            async with SessionLocal() as db:
                row = await db.get(Patient, clinic_record_id)
                return (row.user_id, row.record_status)

        user_id, status = _run(_check())
        self.assertEqual(user_id, self.patient_user.id)
        self.assertEqual(status, "complete")

    def test_self_registration_rejects_foreign_linked_record(self):
        _delete_patient_by_national_id("1000999902")
        self.cleanup_national_ids.append("1000999902")
        created = self.client.post(
            "/patients/",
            json={
                "national_id": "1000999902",
                "full_name": "رکورد متصل",
                "phone": self.patient_phone,
            },
            headers=self._auth(self.admin_token),
        )
        self.assertEqual(created.status_code, 200, created.text)

        # A concurrent patient account (created outside the session context)
        # already owns this record; claiming it again must fail closed.
        _create_user(self.other_phone, role="patient")

        async def _link_other():
            async with SessionLocal() as db:
                other = (
                    await db.execute(
                        select(User).where(User.phone == self.other_phone)
                    )
                ).scalar_one()
                result = await db.execute(
                    select(Patient).where(
                        Patient.national_id == "1000999902"
                    )
                )
                patient = result.scalar_one()
                patient.user_id = other.id
                await db.commit()
                await db.refresh(patient)

        _run(_link_other())
        response = self.client.post(
            "/patients/me",
            json={
                "full_name": "نمی‌توانم رکورد دیگری را بگیرم",
                "phone": self.patient_phone,
                "national_id": "1000999902",
                "relation": "self",
            },
            headers=self._auth(self.patient_token),
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            response.json()["error"]["code"],
            "PATIENT_DUPLICATE_NATIONAL_ID",
        )

    def test_self_registration_rejects_phone_mismatch_on_adoption(self):
        _delete_patient_by_national_id("1000999903")
        self.cleanup_national_ids.append("1000999903")
        created = self.client.post(
            "/patients/",
            json={
                "national_id": "1000999903",
                "full_name": "تلفن متفاوت",
                "phone": "09370005777",
            },
            headers=self._auth(self.admin_token),
        )
        self.assertEqual(created.status_code, 200, created.text)
        response = self.client.post(
            "/patients/me",
            json={
                "full_name": "بی‌تطبیق",
                "phone": "09370005778",
                "national_id": "1000999903",
                "relation": "other",
            },
            headers=self._auth(self.patient_token),
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            response.json()["error"]["code"],
            "PATIENT_DUPLICATE_NATIONAL_ID",
        )

    # ------------------------------------------------- staff completion flow

    def test_staff_update_with_national_id_completes_record(self):
        self.cleanup_national_ids.append("1000999915")
        created = self.client.post(
            "/patients/me",
            json={
                "full_name": "ناقص آزمایشی",
                "phone": self.patient_phone,
                "national_id": "1000999915",
                "relation": "self",
            },
            headers=self._auth(self.patient_token),
        )
        self.assertEqual(created.status_code, 201, created.text)
        record_id = created.json()["id"]

        updated = self.client.put(
            f"/patients/{record_id}",
            json={
                "full_name": "کامل‌شدهٔ پذيرش",
                "phone": self.patient_phone,
                "national_id": "۹۵۰۰۱۱۲۲۳۳",
            },
            headers=self._auth(self.admin_token),
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        body = updated.json()
        # Persian digits are normalized server-side and status re-derived.
        self.assertEqual(body["national_id"], "9500112233")
        self.assertEqual(body["record_status"], "complete")
        self.cleanup_national_ids.append("9500112233")

        # Patient-role callers cannot complete records themselves.
        denied = self.client.put(
            f"/patients/{record_id}",
            json={
                "full_name": "تلاش بیمار",
                "phone": self.patient_phone,
                "national_id": "9500112234",
            },
            headers=self._auth(self.patient_token),
        )
        self.assertEqual(denied.status_code, 403, denied.text)
        _delete_patient_by_national_id("9500112233")

    def test_staff_update_without_national_id_keeps_status_incomplete(self):
        record_id = _create_legacy_incomplete_patient(
            self.patient_user.id, self.patient_phone
        )

        updated = self.client.put(
            f"/patients/{record_id}",
            json={
                "full_name": "نام اصلاح‌شده",
                "phone": self.patient_phone,
            },
            headers=self._auth(self.admin_token),
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        body = updated.json()
        self.assertIsNone(body["national_id"])
        self.assertEqual(body["record_status"], "incomplete")
        self.assertEqual(body["id"], record_id)

    def test_staff_update_with_duplicate_national_id_is_rejected(self):
        _delete_patient_by_national_id("1000999904")
        _delete_patient_by_national_id("1000999905")
        self.cleanup_national_ids.extend(
            ["1000999904", "1000999905"]
        )
        first = self.client.post(
            "/patients/",
            json={
                "national_id": "1000999904",
                "full_name": "اول",
                "phone": "09370005701",
            },
            headers=self._auth(self.admin_token),
        )
        self.assertEqual(first.status_code, 200, first.text)
        second = self.client.post(
            "/patients/",
            json={
                "national_id": "1000999905",
                "full_name": "دوم",
                "phone": "09370005702",
            },
            headers=self._auth(self.admin_token),
        )
        self.assertEqual(second.status_code, 200, second.text)

        conflict = self.client.put(
            f'/patients/{second.json()["id"]}',
            json={
                "full_name": "دوم",
                "phone": "09370005702",
                "national_id": "1000999904",
            },
            headers=self._auth(self.admin_token),
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(
            conflict.json()["error"]["code"],
            "PATIENT_DUPLICATE_NATIONAL_ID",
        )

    # -------------------------------------------------- staff status filter

    def test_admin_can_filter_patients_by_record_status(self):
        incomplete_id = _create_legacy_incomplete_patient(
            self.patient_user.id, self.patient_phone
        )

        _delete_patient_by_national_id("1000999906")
        self.cleanup_national_ids.append("1000999906")
        created = self.client.post(
            "/patients/",
            json={
                "national_id": "1000999906",
                "full_name": "فیلتر کامل",
                "phone": "09370005755",
            },
            headers=self._auth(self.admin_token),
        )
        self.assertEqual(created.status_code, 200, created.text)
        complete_id = created.json()["id"]

        incomplete = self.client.get(
            "/patients/?record_status=incomplete",
            headers=self._auth(self.admin_token),
        )
        self.assertEqual(incomplete.status_code, 200)
        ids = [row["id"] for row in incomplete.json()]
        self.assertIn(incomplete_id, ids)
        self.assertNotIn(complete_id, ids)
        for row in incomplete.json():
            self.assertEqual(row["record_status"], "incomplete")

        complete = self.client.get(
            "/patients/?record_status=complete",
            headers=self._auth(self.admin_token),
        )
        self.assertEqual(complete.status_code, 200)
        ids = [row["id"] for row in complete.json()]
        self.assertIn(complete_id, ids)
        self.assertNotIn(incomplete_id, ids)

        invalid = self.client.get(
            "/patients/?record_status=weird",
            headers=self._auth(self.admin_token),
        )
        self.assertEqual(invalid.status_code, 422, invalid.text)

    def test_patient_without_record_gets_empty_list(self):
        listing = self.client.get(
            "/patients/", headers=self._auth(self.patient_token)
        )
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json(), [])

    # ------------------------------------------- in-chat registration flow

    def _install_chat_llm(self, *responses):
        model = FakeChatModel(*responses)
        app.dependency_overrides[get_chat_llm] = lambda: model
        self.chat_llm_override = True
        return model

    def _chat(self, token, message):
        return self.client.post(
            "/agent/chat",
            json={"message": message},
            headers=self._auth(token),
        )

    def test_unlinked_account_cannot_start_chat(self):
        model = self._install_chat_llm(AIMessage(content="نباید اجرا شود."))
        response = self._chat(self.patient_token, "یک نوبت رزرو کن")
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(
            response.json()["error"]["code"],
            "PATIENT_ACCOUNT_NOT_LINKED",
        )
        # Registration is a hard gate: the model is never invoked.
        self.assertEqual(model.calls, 0)

        listing = self.client.get(
            "/patients/", headers=self._auth(self.patient_token)
        )
        self.assertEqual(listing.json(), [])

    def test_registration_enables_chat_without_form_flag(self):
        self.cleanup_national_ids.append("1000999916")
        register = self.client.post(
            "/patients/me",
            json={
                "full_name": "ثبت‌شده از گفتگو",
                "phone": self.patient_phone,
                "national_id": "1000999916",
                "relation": "self",
            },
            headers=self._auth(self.patient_token),
        )
        self.assertEqual(register.status_code, 201, register.text)
        self.assertEqual(register.json()["record_status"], "complete")

        self._install_chat_llm(AIMessage(content="سلام، در خدمت شما هستم."))
        response = self._chat(self.patient_token, "سلام")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["form_required"])


if __name__ == "__main__":
    unittest.main()
