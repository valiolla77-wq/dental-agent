"""HTTP tests for the staff management APIs.

Covers: admin-only user detail, guarded deletion (self / last admin /
reference detachment), the per-account permission override matrix (read,
replace, invalid actions, non-editable roles) and its effect on
``require_action``, plus the append-only audit trail listing.
"""

import os
import unittest
from datetime import datetime

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only-32-chars-long"
os.environ["APP_ENV"] = "test"
os.environ["OTP_PROVIDER"] = "fake"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.auth.security import create_access_token, hash_password  # noqa: E402
from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.agent_confirmation import AgentConfirmation  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.chat import AgentConversation, AgentMessage  # noqa: E402
from app.models.patient import Patient  # noqa: E402
from app.models.user import User  # noqa: E402

ADMIN_ID = 1
ADMIN_PHONE = "09320000001"
RECEPTION_ID = 2
RECEPTION_PHONE = "09320000002"
RECEPTION_PASSWORD = "Reception!123"
SECOND_ADMIN_ID = 3
SECOND_ADMIN_PHONE = "09320000003"
DOCTOR_USER_ID = 4
PATIENT_USER_ID = 5
PATIENT_PHONE = "09320000005"


class StaffManagementApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False
        )
        await self._seed()

        async def _override_get_db():
            async with self.session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = _override_get_db
        self.client = TestClient(app)

    async def asyncTearDown(self) -> None:
        app.dependency_overrides.pop(get_db, None)
        await self.engine.dispose()

    async def _seed(self) -> None:
        async with self.session_factory() as db:
            db.add_all(
                [
                    User(
                        id=ADMIN_ID,
                        full_name="مدیر اصلی",
                        phone=ADMIN_PHONE,
                        password_hash="hash",
                        role="admin",
                        is_active=True,
                    ),
                    User(
                        id=RECEPTION_ID,
                        full_name="منشی نمونه",
                        phone=RECEPTION_PHONE,
                        password_hash=hash_password(RECEPTION_PASSWORD),
                        role="receptionist",
                        is_active=True,
                    ),
                    User(
                        id=SECOND_ADMIN_ID,
                        full_name="مدیر دوم",
                        phone=SECOND_ADMIN_PHONE,
                        password_hash="hash",
                        role="admin",
                        is_active=True,
                    ),
                    User(
                        id=DOCTOR_USER_ID,
                        full_name="دکتر حساب",
                        phone="09320000004",
                        password_hash="hash",
                        role="doctor",
                        is_active=True,
                    ),
                    User(
                        id=PATIENT_USER_ID,
                        full_name="بیمار حساب‌دار",
                        phone=PATIENT_PHONE,
                        password_hash="hash",
                        role="patient",
                        is_active=True,
                    ),
                ]
            )
            await db.flush()
            db.add(
                Patient(
                    full_name="بیمار متصل",
                    phone=PATIENT_PHONE,
                    user_id=PATIENT_USER_ID,
                    is_account_holder=True,
                )
            )
            conversation = AgentConversation(
                session_id="sess-del-1",
                user_id=PATIENT_USER_ID,
            )
            db.add(conversation)
            await db.flush()
            db.add_all(
                [
                    AgentMessage(
                        conversation_id=conversation.id,
                        role="user",
                        content="سلام",
                    ),
                    AgentMessage(
                        conversation_id=conversation.id,
                        role="assistant",
                        content="درود! چطور می‌توانم کمک کنم؟",
                    ),
                    AgentConfirmation(
                        user_id=PATIENT_USER_ID,
                        session_id="sess-del-1",
                        tool_name="create_appointment",
                        arguments={"patient_id": 1},
                        tool_call_id="call-del-1",
                        token_hash="a" * 64,
                        created_at=datetime(2030, 1, 1),
                        expires_at=datetime(2030, 1, 2),
                    ),
                ]
            )
            await db.commit()

    def _headers(self, user_id: int) -> dict[str, str]:
        token = create_access_token(subject=str(user_id))
        return {"Authorization": f"Bearer {token}"}

    # --- user detail -----------------------------------------------------

    async def test_user_detail_is_admin_only(self) -> None:
        for role_id in (RECEPTION_ID, DOCTOR_USER_ID, PATIENT_USER_ID):
            response = self.client.get(
                f"/users/{RECEPTION_ID}", headers=self._headers(role_id)
            )
            self.assertEqual(response.status_code, 403)
        response = self.client.get(
            f"/users/{RECEPTION_ID}", headers=self._headers(ADMIN_ID)
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], RECEPTION_ID)
        self.assertNotIn("password_hash", body)

    async def test_user_detail_404_for_missing(self) -> None:
        response = self.client.get("/users/9999", headers=self._headers(ADMIN_ID))
        self.assertEqual(response.status_code, 404)

    # --- deletion --------------------------------------------------------

    async def test_admin_cannot_delete_self_or_last_admin(self) -> None:
        response = self.client.delete(
            f"/users/{ADMIN_ID}", headers=self._headers(ADMIN_ID)
        )
        self.assertEqual(response.status_code, 409)

        # Deleting another admin is allowed while a second active admin
        # remains in charge of the system.
        response = self.client.delete(
            f"/users/{SECOND_ADMIN_ID}", headers=self._headers(ADMIN_ID)
        )
        self.assertEqual(response.status_code, 200)

        # A token of the removed account is dead immediately afterwards:
        # the account no longer exists, so the request fails closed (401).
        response = self.client.get(
            "/users/", headers=self._headers(SECOND_ADMIN_ID)
        )
        self.assertEqual(response.status_code, 401)

    async def test_delete_user_detaches_references(self) -> None:
        response = self.client.delete(
            f"/users/{PATIENT_USER_ID}", headers=self._headers(ADMIN_ID)
        )
        self.assertEqual(response.status_code, 200)

        async with self.session_factory() as db:
            row = await db.get(User, PATIENT_USER_ID)
            self.assertIsNone(row)
            patient = await db.scalar(
                select(Patient).where(Patient.phone == PATIENT_PHONE)
            )
            self.assertIsNotNone(patient)
            self.assertIsNone(patient.user_id)
            self.assertFalse(patient.is_account_holder)

    async def test_delete_user_removes_agent_data(self) -> None:
        """Deleting an account that owns agent history must not 500.

        Regression: the previous detach-by-NULL update violated the NOT NULL
        constraint on ``agent_conversations.user_id`` (IntegrityError). The
        account's private conversations, their messages and pending
        confirmations are removed outright instead.
        """
        async with self.session_factory() as db:
            before_conversations = await db.scalar(
                select(AgentConversation).where(
                    AgentConversation.user_id == PATIENT_USER_ID
                )
            )
            self.assertIsNotNone(before_conversations)

        response = self.client.delete(
            f"/users/{PATIENT_USER_ID}", headers=self._headers(ADMIN_ID)
        )
        self.assertEqual(response.status_code, 200)

        async with self.session_factory() as db:
            self.assertIsNone(await db.get(User, PATIENT_USER_ID))
            self.assertIsNone(
                await db.scalar(
                    select(AgentConversation).where(
                        AgentConversation.session_id == "sess-del-1"
                    )
                )
            )
            self.assertEqual(
                list(
                    await db.scalars(
                        select(AgentMessage).where(
                            AgentMessage.content == "سلام"
                        )
                    )
                ),
                [],
            )
            self.assertIsNone(
                await db.scalar(
                    select(AgentConfirmation).where(
                        AgentConfirmation.user_id == PATIENT_USER_ID
                    )
                )
            )

    async def test_user_update_clears_overrides_on_role_change(self) -> None:
        await self._set_overrides(RECEPTION_ID, {"patient:delete": "allow"})
        response = self.client.put(
            f"/users/{RECEPTION_ID}",
            json={"role": "doctor"},
            headers=self._headers(ADMIN_ID),
        )
        self.assertEqual(response.status_code, 200)
        async with self.session_factory() as db:
            user = await db.get(User, RECEPTION_ID)
            self.assertEqual(user.role, "doctor")
            self.assertIsNone(user.permission_overrides)

    async def test_cannot_demote_last_active_admin(self) -> None:
        # Demoting another admin is allowed while a second active admin
        # remains; the demoted account keeps working with its new role.
        response = self.client.put(
            f"/users/{SECOND_ADMIN_ID}",
            json={"role": "receptionist"},
            headers=self._headers(ADMIN_ID),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["role"], "receptionist")

        # An admin cannot demote or deactivate their own account (the
        # surviving-admin invariant is guarded at every write path).
        response = self.client.put(
            f"/users/{ADMIN_ID}",
            json={"role": "receptionist"},
            headers=self._headers(ADMIN_ID),
        )
        self.assertEqual(response.status_code, 409)

    # --- permission overrides ---------------------------------------------

    async def test_permissions_matrix_roundtrip(self) -> None:
        response = self.client.get(
            f"/users/{RECEPTION_ID}/permissions", headers=self._headers(ADMIN_ID)
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["role"], "receptionist")
        actions = {item["action"]: item for item in body["actions"]}
        self.assertTrue(actions["patient:create"]["effective"])
        self.assertFalse(actions["patient:delete"]["effective"])

        # Pin an explicit deny on a default-allowed action and an allow on a
        # default-forbidden one.
        response = self.client.put(
            f"/users/{RECEPTION_ID}/permissions",
            json={"overrides": {"patient:create": "deny", "report:overview": "allow"}},
            headers=self._headers(ADMIN_ID),
        )
        self.assertEqual(response.status_code, 200)
        actions = {item["action"]: item for item in response.json()["actions"]}
        self.assertFalse(actions["patient:create"]["effective"])
        self.assertEqual(actions["patient:create"]["override"], "deny")
        self.assertTrue(actions["report:overview"]["effective"])
        self.assertEqual(actions["report:overview"]["override"], "allow")

        # Clearing back to role defaults.
        response = self.client.put(
            f"/users/{RECEPTION_ID}/permissions",
            json={"overrides": {}},
            headers=self._headers(ADMIN_ID),
        )
        self.assertEqual(response.status_code, 200)
        actions = {item["action"]: item for item in response.json()["actions"]}
        self.assertIsNone(actions["patient:create"]["override"])
        self.assertTrue(actions["patient:create"]["effective"])

    async def test_unknown_permission_action_rejected(self) -> None:
        response = self.client.put(
            f"/users/{RECEPTION_ID}/permissions",
            json={"overrides": {"not:a:real:action": "allow"}},
            headers=self._headers(ADMIN_ID),
        )
        self.assertEqual(response.status_code, 422)

    async def test_permissions_not_editable_for_admin_or_patient(self) -> None:
        for target in (SECOND_ADMIN_ID, PATIENT_USER_ID):
            response = self.client.put(
                f"/users/{target}/permissions",
                json={"overrides": {"patient:read": "deny"}},
                headers=self._headers(ADMIN_ID),
            )
            self.assertEqual(response.status_code, 409)
            self.assertEqual(
                response.json().get("error", {}).get("code"),
                "USER_PERMISSIONS_NOT_EDITABLE",
            )

    async def test_permissions_endpoints_are_admin_only(self) -> None:
        response = self.client.get(
            f"/users/{RECEPTION_ID}/permissions",
            headers=self._headers(RECEPTION_ID),
        )
        self.assertEqual(response.status_code, 403)
        response = self.client.put(
            f"/users/{DOCTOR_USER_ID}/permissions",
            json={"overrides": {}},
            headers=self._headers(RECEPTION_ID),
        )
        self.assertEqual(response.status_code, 403)

    async def test_override_changes_real_authorization(self) -> None:
        """The override must influence require_action, not just the matrix UI."""
        from app.auth.permissions import require_action
        from app.errors import AppError

        async with self.session_factory() as db:
            reception = await db.get(User, RECEPTION_ID)
            self.assertIsNotNone(reception)

            # Default: receptionist may create patients.
            require_action(reception, "patient:create")
            # Default: receptionist may NOT delete patients.
            with self.assertRaises(AppError):
                require_action(reception, "patient:delete")

            reception.permission_overrides = {
                "patient:create": "deny",
                "patient:delete": "allow",
            }
            with self.assertRaises(AppError):
                require_action(reception, "patient:create")
            require_action(reception, "patient:delete")

            # Overrides never apply to admins or patients.
            admin = await db.get(User, ADMIN_ID)
            admin.permission_overrides = {"report:overview": "deny"}
            require_action(admin, "report:overview")

            patient = await db.get(User, PATIENT_USER_ID)
            patient.permission_overrides = {"patient:create": "allow"}
            with self.assertRaises(AppError):
                require_action(patient, "patient:create")

    # --- audit trail -------------------------------------------------------

    async def test_audit_logs_record_sensitive_actions(self) -> None:
        self.client.delete(
            f"/users/{PATIENT_USER_ID}", headers=self._headers(ADMIN_ID)
        )
        self.client.put(
            f"/users/{RECEPTION_ID}/permissions",
            json={"overrides": {"patient:create": "deny"}},
            headers=self._headers(ADMIN_ID),
        )
        response = self.client.get(
            "/audit-logs/", headers=self._headers(ADMIN_ID)
        )
        self.assertEqual(response.status_code, 200)
        items = response.json()
        actions = [item["action"] for item in items]
        self.assertIn("user.delete", actions)
        self.assertIn("user.permissions.update", actions)
        delete_row = next(
            item for item in items if item["action"] == "user.delete"
        )
        self.assertEqual(delete_row["actor_user_id"], ADMIN_ID)
        self.assertEqual(delete_row["target_user_id"], PATIENT_USER_ID)
        self.assertEqual(delete_row["detail"]["role"], "patient")

    async def test_audit_logs_are_admin_only_and_filterable(self) -> None:
        self.client.put(
            f"/users/{RECEPTION_ID}",
            json={"is_active": False},
            headers=self._headers(ADMIN_ID),
        )
        # A non-admin account may read the trail only through a 403.
        response = self.client.get(
            "/audit-logs/", headers=self._headers(PATIENT_USER_ID)
        )
        self.assertEqual(response.status_code, 403)

        response = self.client.get(
            "/audit-logs/?action=user.update", headers=self._headers(ADMIN_ID)
        )
        self.assertEqual(response.status_code, 200)
        items = response.json()
        self.assertGreaterEqual(len(items), 1)
        self.assertTrue(all(item["action"] == "user.update" for item in items))

    # --- helpers -----------------------------------------------------------

    async def _set_active(self, user_id: int, active: bool) -> None:
        async with self.session_factory() as db:
            user = await db.get(User, user_id)
            user.is_active = active
            await db.commit()

    async def _set_overrides(self, user_id: int, overrides: dict) -> None:
        async with self.session_factory() as db:
            user = await db.get(User, user_id)
            user.permission_overrides = dict(overrides)
            await db.commit()


if __name__ == "__main__":
    unittest.main()
