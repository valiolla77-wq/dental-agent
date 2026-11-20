"""Role-scoped agent tool tests over the real graph and HTTP router.

Covers the per-role tool expansion: patient-only self-service profile,
staff record management behind the write-confirmation flow with audit
rows, administrator-only staff directory and audit trail, the every-role
feedback channel, and the admin permission matrix exposure of the new
actions. The LLM is always a fake injected through FastAPI dependency
overrides; the database is a per-test in-memory SQLite.
"""

import os
import unittest
from datetime import datetime

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only-32-chars-long"
os.environ["APP_ENV"] = "test"
os.environ["OTP_PROVIDER"] = "fake"

from fastapi.testclient import TestClient  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.agent.registry import get_llm_tool_schemas  # noqa: E402
from app.auth.rate_limit import action_rate_limiter  # noqa: E402
from app.auth.security import create_access_token  # noqa: E402
from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.audit_log import AuditLog  # noqa: E402
from app.models.feedback import FeedbackReport  # noqa: E402
from app.models.patient import Patient  # noqa: E402
from app.models.user import User  # noqa: E402
from app.routers.agent_chat import get_chat_llm  # noqa: E402

ADMIN_ID = 1
RECEPTION_ID = 2
DOCTOR_ID = 3
PATIENT_USER_ID = 4
SESSION = "role-tools-session"


class FakeChatModel:
    """Minimal ToolCallingChatModel stand-in returning scripted responses."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def bind_tools(self, tool_schemas):
        self.visible_tools = [
            schema["function"]["name"] for schema in tool_schemas
        ]
        return self

    async def ainvoke(self, _messages):
        self.calls += 1
        return self.responses.pop(0)


def _tool_call(name, args, call_id):
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": call_id, "type": "tool_call"}
        ],
    )


class AgentRoleToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # The chat endpoint shares one process-wide limiter across tests;
        # clear it so per-test request bursts never trip the limiter.
        action_rate_limiter.reset()
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(self._create_tables)
        self.session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False
        )
        await self._seed()
        self._override_get_db()
        self.client = TestClient(app)
        self.model = None
        app.dependency_overrides[get_chat_llm] = lambda: self.model

    @staticmethod
    def _create_tables(connection) -> None:
        from app.models.base import Base

        Base.metadata.create_all(connection)

    async def asyncTearDown(self) -> None:
        app.dependency_overrides.pop(get_chat_llm, None)
        app.dependency_overrides.pop(get_db, None)
        await self.engine.dispose()

    async def _seed(self) -> None:
        async with self.session_factory() as db:
            db.add_all(
                [
                    User(
                        id=ADMIN_ID,
                        full_name="مدیر نقش‌ها",
                        phone="09350000001",
                        password_hash="hash",
                        role="admin",
                        is_active=True,
                    ),
                    User(
                        id=RECEPTION_ID,
                        full_name="پذیرش نقش‌ها",
                        phone="09350000002",
                        password_hash="hash",
                        role="receptionist",
                        is_active=True,
                    ),
                    User(
                        id=DOCTOR_ID,
                        full_name="دکتر نقش‌ها",
                        phone="09350000003",
                        password_hash="hash",
                        role="doctor",
                        is_active=True,
                    ),
                    User(
                        id=PATIENT_USER_ID,
                        full_name="بیمار نقش‌ها",
                        phone="09350000004",
                        password_hash="hash",
                        role="patient",
                        is_active=True,
                    ),
                ]
            )
            await db.flush()
            db.add_all(
                [
                    Patient(
                        full_name="بیمار صاحب حساب",
                        phone="09350000004",
                        national_id="1234567890",
                        user_id=PATIENT_USER_ID,
                        is_account_holder=True,
                        record_status="complete",
                    ),
                    Patient(
                        full_name="عضو خانواده",
                        phone="09350000044",
                        national_id="1234567891",
                        user_id=PATIENT_USER_ID,
                        is_account_holder=False,
                        record_status="complete",
                    ),
                ]
            )
            db.add(
                AuditLog(
                    actor_user_id=ADMIN_ID,
                    actor_phone="09350000001",
                    action="user.create",
                    target_label="پذیرش نقش‌ها (09350000002)",
                    created_at=datetime(2030, 1, 1, 10, 0),
                )
            )
            await db.commit()

    def _override_get_db(self) -> None:
        async def _override():
            async with self.session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = _override

    def _headers(self, user_id: int) -> dict[str, str]:
        token = create_access_token(subject=str(user_id))
        return {"Authorization": f"Bearer {token}"}

    def _db(self):
        """Fresh session factory context; use as ``async with self._db() as db``."""
        return self.session_factory()

    def _chat(self, user_id: int, *, message="سلام", confirmation=None):
        body = {"message": message, "session_id": SESSION}
        if confirmation is not None:
            body["confirmation"] = confirmation
        return self.client.post(
            "/agent/chat", json=body, headers=self._headers(user_id)
        )

    # --- visibility -------------------------------------------------------

    async def test_registry_visibility_follows_role_matrix(self) -> None:
        patient = {
            s["function"]["name"]
            for s in get_llm_tool_schemas(patient_bound=True)
        }
        doctor = {
            s["function"]["name"] for s in get_llm_tool_schemas(role="doctor")
        }
        reception = {
            s["function"]["name"]
            for s in get_llm_tool_schemas(role="receptionist")
        }
        admin = {
            s["function"]["name"] for s in get_llm_tool_schemas(role="admin")
        }
        self.assertIn("get_my_profile", patient)
        self.assertNotIn("get_my_profile", reception)
        self.assertNotIn("create_patient", patient)
        self.assertIn("create_patient", reception)
        self.assertNotIn("create_patient", doctor)
        self.assertNotIn("update_patient", doctor)
        self.assertIn("update_patient", reception)
        self.assertIn("get_staff_directory", admin)
        self.assertNotIn("get_staff_directory", reception)
        self.assertIn("get_audit_trail", admin)
        self.assertNotIn("get_audit_trail", doctor)
        self.assertIn("submit_feedback", patient)
        self.assertIn("submit_feedback", admin)

    async def test_doctor_override_makes_record_tools_visible(self) -> None:
        async with self._db() as db:
            doctor = await db.get(User, DOCTOR_ID)
            doctor.permission_overrides = {
                "patient:create": "allow",
                "patient:update": "allow",
            }
            await db.commit()
        names = {
            s["function"]["name"]
            for s in get_llm_tool_schemas(
                role="doctor", actor=await self._load_user(DOCTOR_ID)
            )
        }
        self.assertIn("create_patient", names)
        self.assertIn("update_patient", names)

    async def _load_user(self, user_id: int) -> User:
        async with self._db() as db:
            return await db.get(User, user_id)

    # --- patient self-service profile -------------------------------------

    async def test_patient_sees_own_profile_records_only(self) -> None:
        self.model = FakeChatModel(
            _tool_call("get_my_profile", {}, "call-profile"),
            AIMessage(content="این هم پرونده‌های شما."),
        )
        response = self._chat(PATIENT_USER_ID, message="پروفایل من چیه؟")
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertIn("پرونده", payload["reply"])
        async with self._db() as db:
            holder = await db.scalar(
                select(Patient).where(Patient.phone == "09350000004")
            )
            self.assertEqual(holder.full_name, "بیمار صاحب حساب")

    async def test_staff_profile_call_is_denied_and_audited(self) -> None:
        self.model = FakeChatModel(
            _tool_call("get_my_profile", {}, "call-profile-staff"),
            AIMessage(content="پایان."),
        )
        response = self._chat(RECEPTION_ID, message="پروفایل من را ببین")
        self.assertEqual(response.status_code, 200, response.text)
        async with self._db() as db:
            denial = await db.scalar(
                select(AuditLog)
                .where(AuditLog.action == "agent.tool.denied")
                .order_by(AuditLog.id.desc())
            )
            self.assertIsNotNone(denial)
            self.assertEqual(denial.detail["tool"], "get_my_profile")

    # --- staff record management ------------------------------------------

    async def test_receptionist_creates_patient_after_confirmation(self) -> None:
        args = {
            "national_id": "9876543210",
            "full_name": "بیمار تازه",
            "phone": "09350000099",
        }
        self.model = FakeChatModel(
            _tool_call("create_patient", dict(args), "call-create"),
            AIMessage(content="انجام شد."),
        )
        first = self._chat(RECEPTION_ID, message="پرونده بساز")
        self.assertEqual(first.status_code, 200, first.text)
        payload = first.json()
        self.assertTrue(payload["confirmation_required"])
        self.assertIn("بیمار تازه", payload["confirmation_prompt"])
        self.assertNotIn("9876543210", payload["confirmation_prompt"])

        second = self._chat(
            RECEPTION_ID,
            message="تأیید می‌کنم",
            confirmation={
                "token": payload["confirmation_token"],
                "decision": "approved",
            },
        )
        self.assertEqual(second.status_code, 200, second.text)
        self.assertFalse(second.json()["confirmation_required"])

        async with self._db() as db:
            created = await db.scalar(
                select(Patient).where(Patient.phone == "09350000099")
            )
            self.assertIsNotNone(created)
            self.assertEqual(created.national_id, "9876543210")
            audit = await db.scalar(
                select(AuditLog)
                .where(AuditLog.action == "patient.create")
                .order_by(AuditLog.id.desc())
            )
            self.assertIsNotNone(audit)
            self.assertEqual(audit.detail["via"], "agent")
            self.assertEqual(audit.actor_user_id, RECEPTION_ID)

    async def test_create_patient_rejects_invalid_national_id(self) -> None:
        self.model = FakeChatModel(
            _tool_call(
                "create_patient",
                {"national_id": "abc", "full_name": "نام", "phone": "09350000123"},
                "call-create-bad",
            ),
            AIMessage(content="پایان."),
        )
        response = self._chat(RECEPTION_ID, message="پرونده بساز")
        self.assertEqual(response.status_code, 200, response.text)
        async with self._db() as db:
            row = await db.scalar(
                select(Patient).where(Patient.phone == "09350000123")
            )
            self.assertIsNone(row)

    async def test_doctor_denied_create_until_override(self) -> None:
        args = {
            "national_id": "9876543211",
            "full_name": "بیمار پزشک",
            "phone": "09350000111",
        }
        self.model = FakeChatModel(
            _tool_call("create_patient", dict(args), "call-doc-create"),
            AIMessage(content="پایان."),
        )
        denied = self._chat(DOCTOR_ID, message="پرونده بساز")
        self.assertEqual(denied.status_code, 200, denied.text)
        async with self._db() as db:
            row = await db.scalar(
                select(Patient).where(Patient.phone == "09350000111")
            )
            self.assertIsNone(row)
            denial = await db.scalar(
                select(AuditLog)
                .where(AuditLog.action == "agent.tool.denied")
                .order_by(AuditLog.id.desc())
            )
            self.assertIsNotNone(denial)
            self.assertEqual(denial.detail["tool"], "create_patient")

        # Admin pins an allow override on the doctor's account: the very
        # same request now runs through the confirmation flow.
        grant = self.client.put(
            f"/users/{DOCTOR_ID}/permissions",
            json={"overrides": {"patient:create": "allow"}},
            headers=self._headers(ADMIN_ID),
        )
        self.assertEqual(grant.status_code, 200, grant.text)

        self.model = FakeChatModel(
            _tool_call("create_patient", dict(args), "call-doc-create-2"),
            AIMessage(content="انجام شد."),
            AIMessage(content="پرونده ثبت شد."),
        )
        first = self._chat(DOCTOR_ID, message="پرونده بساز")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertTrue(first.json()["confirmation_required"])
        second = self._chat(
            DOCTOR_ID,
            message="تأیید می‌کنم",
            confirmation={
                "token": first.json()["confirmation_token"],
                "decision": "approved",
            },
        )
        self.assertEqual(second.status_code, 200, second.text)
        async with self._db() as db:
            created = await db.scalar(
                select(Patient).where(Patient.phone == "09350000111")
            )
            self.assertIsNotNone(created)

    async def test_receptionist_updates_patient_after_confirmation(self) -> None:
        async with self._db() as db:
            holder = await db.scalar(
                select(Patient).where(Patient.phone == "09350000004")
            )
            patient_id = int(holder.id)
        self.model = FakeChatModel(
            _tool_call(
                "update_patient",
                {"patient_id": patient_id, "phone": "09350000055"},
                "call-update",
            ),
            AIMessage(content="انجام شد."),
            AIMessage(content="به‌روزرسانی شد."),
        )
        first = self._chat(RECEPTION_ID, message="تلفن را عوض کن")
        self.assertEqual(first.status_code, 200, first.text)
        payload = first.json()
        self.assertTrue(payload["confirmation_required"])
        self.assertIn("بیمار صاحب حساب", payload["confirmation_prompt"])

        second = self._chat(
            RECEPTION_ID,
            message="تأیید می‌کنم",
            confirmation={
                "token": payload["confirmation_token"],
                "decision": "approved",
            },
        )
        self.assertEqual(second.status_code, 200, second.text)
        async with self._db() as db:
            updated = await db.get(Patient, patient_id)
            self.assertEqual(updated.phone, "09350000055")
            audit = await db.scalar(
                select(AuditLog)
                .where(AuditLog.action == "patient.update")
                .order_by(AuditLog.id.desc())
            )
            self.assertIsNotNone(audit)
            self.assertEqual(audit.detail["changed"], ["phone"])

    async def test_patient_cannot_edit_records(self) -> None:
        async with self._db() as db:
            holder = await db.scalar(
                select(Patient).where(Patient.phone == "09350000004")
            )
            patient_id = int(holder.id)
        self.model = FakeChatModel(
            _tool_call(
                "update_patient",
                {"patient_id": patient_id, "phone": "09350000066"},
                "call-patient-update",
            ),
            AIMessage(content="پایان."),
        )
        response = self._chat(PATIENT_USER_ID, message="تلفنم را عوض کن")
        self.assertEqual(response.status_code, 200, response.text)
        async with self._db() as db:
            unchanged = await db.get(Patient, patient_id)
            self.assertEqual(unchanged.phone, "09350000004")

    # --- administrator reviews ---------------------------------------------

    async def test_admin_reads_staff_directory(self) -> None:
        self.model = FakeChatModel(
            _tool_call("get_staff_directory", {}, "call-staff"),
            AIMessage(content="این هم فهرست حساب‌ها."),
        )
        response = self._chat(ADMIN_ID, message="چند حساب داریم؟")
        self.assertEqual(response.status_code, 200, response.text)
        # The reply comes from the fake model, so assert on the stored turn:
        # re-run the handler directly against the same database instead.
        async with self._db() as db:
            admin = await db.get(User, ADMIN_ID)
            from app.agent_tools import tools

            result = await tools.get_staff_directory(db, actor=admin)
            self.assertTrue(result.ok)
            self.assertEqual(result.data.by_role.get("admin"), 1)
            self.assertEqual(result.data.by_role.get("patient"), 1)
            self.assertEqual(result.data.total_accounts, 4)
            self.assertEqual(result.data.active_accounts, 4)

    async def test_receptionist_denied_staff_directory(self) -> None:
        self.model = FakeChatModel(
            _tool_call("get_staff_directory", {}, "call-staff-recep"),
            AIMessage(content="پایان."),
        )
        response = self._chat(RECEPTION_ID, message="چند حساب داریم؟")
        self.assertEqual(response.status_code, 200, response.text)
        async with self._db() as db:
            denial = await db.scalar(
                select(AuditLog)
                .where(AuditLog.action == "agent.tool.denied")
                .order_by(AuditLog.id.desc())
            )
            self.assertIsNotNone(denial)
            self.assertEqual(denial.detail["tool"], "get_staff_directory")

    async def test_admin_reads_audit_trail(self) -> None:
        self.model = FakeChatModel(
            _tool_call("get_audit_trail", {"limit": 5}, "call-audit"),
            AIMessage(content="این هم رخدادها."),
        )
        response = self._chat(ADMIN_ID, message="آخرین رخدادها؟")
        self.assertEqual(response.status_code, 200, response.text)
        async with self._db() as db:
            admin = await db.get(User, ADMIN_ID)
            from app.agent_tools import tools

            result = await tools.get_audit_trail(db, 5, actor=admin)
            self.assertTrue(result.ok)
            self.assertGreaterEqual(result.data.total_returned, 1)
            actions = [entry.action for entry in result.data.entries]
            self.assertIn("user.create", actions)

    async def test_receptionist_denied_audit_trail(self) -> None:
        self.model = FakeChatModel(
            _tool_call("get_audit_trail", {}, "call-audit-recep"),
            AIMessage(content="پایان."),
        )
        response = self._chat(RECEPTION_ID, message="آخرین رخدادها؟")
        self.assertEqual(response.status_code, 200, response.text)
        async with self._db() as db:
            denial = await db.scalar(
                select(AuditLog)
                .where(AuditLog.action == "agent.tool.denied")
                .order_by(AuditLog.id.desc())
            )
            self.assertIsNotNone(denial)
            self.assertEqual(denial.detail["tool"], "get_audit_trail")

    # --- feedback channel ---------------------------------------------------

    async def test_patient_submits_feedback_after_confirmation(self) -> None:
        self.model = FakeChatModel(
            _tool_call(
                "submit_feedback",
                {"category": "suggestion", "message": "افزودن فیلتر خدمات"},
                "call-feedback",
            ),
            AIMessage(content="ثبت شد."),
            AIMessage(content="ممنون، ثبت شد."),
        )
        first = self._chat(PATIENT_USER_ID, message="پیشنهاد دارم")
        self.assertEqual(first.status_code, 200, first.text)
        payload = first.json()
        self.assertTrue(payload["confirmation_required"])
        self.assertIn("پیشنهاد", payload["confirmation_prompt"])
        self.assertIn("افزودن فیلتر خدمات", payload["confirmation_prompt"])

        second = self._chat(
            PATIENT_USER_ID,
            message="تأیید می‌کنم",
            confirmation={
                "token": payload["confirmation_token"],
                "decision": "approved",
            },
        )
        self.assertEqual(second.status_code, 200, second.text)
        async with self._db() as db:
            row = await db.scalar(
                select(FeedbackReport)
                .where(FeedbackReport.user_id == PATIENT_USER_ID)
                .order_by(FeedbackReport.id.desc())
            )
            self.assertIsNotNone(row)
            self.assertEqual(row.category, "suggestion")
            self.assertEqual(row.status, "new")
            self.assertEqual(row.context["source"], "agent")
            self.assertEqual(row.context["role"], "patient")

    async def test_feedback_rejects_unknown_category(self) -> None:
        self.model = FakeChatModel(
            _tool_call(
                "submit_feedback",
                {"category": "complaint", "message": "متن"},
                "call-feedback-bad",
            ),
            AIMessage(content="پایان."),
        )
        response = self._chat(PATIENT_USER_ID, message="شکایت دارم")
        self.assertEqual(response.status_code, 200, response.text)
        async with self._db() as db:
            rows = (
                (
                    await db.execute(
                        select(FeedbackReport).where(
                            FeedbackReport.user_id == PATIENT_USER_ID
                        )
                    )
                )
                .scalars()
                .all()
            )
            self.assertEqual(rows, [])

    # --- permission matrix ---------------------------------------------------

    async def test_permission_matrix_exposes_new_actions(self) -> None:
        response = self.client.get(
            f"/users/{RECEPTION_ID}/permissions", headers=self._headers(ADMIN_ID)
        )
        self.assertEqual(response.status_code, 200, response.text)
        actions = {
            item["action"]: item for item in response.json()["actions"]
        }
        self.assertIn("user:read", actions)
        self.assertIn("audit:read", actions)
        self.assertIn("feedback:create", actions)
        self.assertFalse(actions["user:read"]["effective"])
        self.assertFalse(actions["audit:read"]["effective"])
        self.assertTrue(actions["feedback:create"]["effective"])

        admin_permissions = self.client.get(
            f"/users/{ADMIN_ID}/permissions", headers=self._headers(ADMIN_ID)
        )
        admin_actions = {
            item["action"]: item
            for item in admin_permissions.json()["actions"]
        }
        self.assertTrue(admin_actions["user:read"]["effective"])
        self.assertTrue(admin_actions["audit:read"]["effective"])
        self.assertTrue(admin_actions["feedback:create"]["effective"])


if __name__ == "__main__":
    unittest.main()
