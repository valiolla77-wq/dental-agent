"""End-to-end tests for persisted agent write confirmations over HTTP.

The LLM is always a fake injected through FastAPI dependency overrides, so no
provider or network access is required. Appointments and users use the
process-wide temporary in-memory test database; the real database is never
touched.
"""

import asyncio
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

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
from sqlalchemy import delete, select  # noqa: E402

from app.agent import agent_graph  # noqa: E402
from app.agent import confirmations as confirmations_module  # noqa: E402
from app.auth.security import create_access_token, hash_password  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.agent_confirmation import AgentConfirmation  # noqa: E402
from app.models.appointment import Appointment  # noqa: E402
from app.models.user import User  # noqa: E402
from app.routers import agent_chat as agent_chat_module  # noqa: E402
from app.routers.agent_chat import get_chat_llm  # noqa: E402


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


class CapturingGraph:
    """Delegate to the real graph while recording each trusted context."""

    def __init__(self, graph):
        self.graph = graph
        self.contexts = []

    async def ainvoke(self, state, context=None):
        self.contexts.append(context)
        return await self.graph.ainvoke(state, context=context)


def _cancel_call(appointment_id, call_id="call-cancel-1"):
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "cancel_appointment",
                "args": {"appointment_id": appointment_id},
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )


def _run(coro):
    return asyncio.run(coro)


def _create_user(phone, role="receptionist"):
    async def _create():
        async with SessionLocal() as db:
            user = User(
                full_name="Agent Chat Probe",
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


def _delete_user(phone):
    async def _delete():
        async with SessionLocal() as db:
            user = (
                await db.execute(select(User).where(User.phone == phone))
            ).scalar_one_or_none()
            if user is not None:
                await db.execute(
                    delete(AgentConfirmation).where(
                        AgentConfirmation.user_id == user.id
                    )
                )
            await db.execute(delete(User).where(User.phone == phone))
            await db.commit()

    _run(_delete())


def _delete_confirmations(user_id):
    async def _delete():
        async with SessionLocal() as db:
            await db.execute(
                delete(AgentConfirmation).where(
                    AgentConfirmation.user_id == user_id
                )
            )
            await db.commit()

    _run(_delete())


def _create_appointment():
    async def _create():
        async with SessionLocal() as db:
            appointment = Appointment(
                patient_id=1,
                doctor_id=1,
                service_id=1,
                appointment_time=datetime(2030, 1, 1, 10, 0),
                status="scheduled",
            )
            db.add(appointment)
            await db.commit()
            await db.refresh(appointment)
            return appointment.id

    return _run(_create())


def _delete_appointment(appointment_id):
    async def _delete():
        async with SessionLocal() as db:
            appointment = await db.get(Appointment, appointment_id)
            if appointment is not None:
                await db.delete(appointment)
                await db.commit()

    _run(_delete())


def _appointment_status(appointment_id):
    async def _fetch():
        async with SessionLocal() as db:
            appointment = await db.get(Appointment, appointment_id)
            return None if appointment is None else appointment.status

    return _run(_fetch())


def _confirmation_row(user_id, session_id):
    async def _fetch():
        async with SessionLocal() as db:
            result = await db.execute(
                select(AgentConfirmation)
                .where(
                    AgentConfirmation.user_id == user_id,
                    AgentConfirmation.session_id == session_id,
                )
                .order_by(AgentConfirmation.id.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return {
                "id": row.id,
                "user_id": row.user_id,
                "session_id": row.session_id,
                "tool_name": row.tool_name,
                "arguments": dict(row.arguments),
                "tool_call_id": row.tool_call_id,
                "token_hash": row.token_hash,
                "created_at": row.created_at,
                "expires_at": row.expires_at,
                "consumed_at": row.consumed_at,
                "decision": row.decision,
            }

    return _run(_fetch())


class AgentChatIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _run(init_db())

    def setUp(self):
        self.client = TestClient(app)
        self.phone_a = "09360002001"
        self.phone_b = "09360002002"
        _delete_user(self.phone_a)
        _delete_user(self.phone_b)
        self.user_a = _create_user(self.phone_a, role="receptionist")
        self.user_b = _create_user(self.phone_b, role="receptionist")
        self.token_a = create_access_token(subject=str(self.user_a.id))
        self.token_b = create_access_token(subject=str(self.user_b.id))
        self.appointment_id = None

    def tearDown(self):
        app.dependency_overrides.pop(get_chat_llm, None)
        if self.appointment_id is not None:
            _delete_appointment(self.appointment_id)
        _delete_confirmations(self.user_a.id)
        _delete_confirmations(self.user_b.id)
        _delete_user(self.phone_a)
        _delete_user(self.phone_b)

    def _install_llm(self, model):
        app.dependency_overrides[get_chat_llm] = lambda: model

    def _post(
        self,
        token=None,
        *,
        message="سلام",
        session_id=None,
        confirmation=None,
    ):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        body = {"message": message}
        if session_id is not None:
            body["session_id"] = session_id
        if confirmation is not None:
            body["confirmation"] = confirmation
        return self.client.post("/agent/chat", json=body, headers=headers)

    def _issue_write(self, token, session_id, appointment_id, model):
        """Create a pending cancellation and return (response, confirmation token)."""
        self._install_llm(model)
        response = self._post(
            token,
            message="این نوبت را لغو کن",
            session_id=session_id,
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["confirmation_required"])
        self.assertTrue(payload["confirmation_token"])
        return response, payload["confirmation_token"]

    def _approve(self, token, session_id, confirmation_token, decision="approved"):
        return self._post(
            token,
            message="تأیید می‌کنم",
            session_id=session_id,
            confirmation={
                "token": confirmation_token,
                "decision": decision,
            },
        )

    def test_anonymous_request_is_rejected_with_401(self):
        self._install_llm(FakeChatModel(AIMessage(content="unused")))
        response = self._post()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "COMMON_UNAUTHORIZED")

    def test_authenticated_request_propagates_user_identity_to_context(self):
        model = FakeChatModel(AIMessage(content="پاسخ آزمایشی"))
        self._install_llm(model)
        capture = CapturingGraph(agent_graph)
        with patch.object(agent_chat_module, "agent_graph", capture):
            response = self._post(self.token_a, session_id="shared")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "پاسخ آزمایشی")
        self.assertEqual(response.json()["session_id"], "shared")
        self.assertEqual(len(capture.contexts), 1)
        context = capture.contexts[0]
        self.assertEqual(context["actor"].id, self.user_a.id)
        self.assertEqual(context["actor"].role, "receptionist")
        self.assertEqual(context["session_id"], "shared")
        self.assertIsNotNone(context["db"])
        self.assertIsInstance(context["llm"], FakeChatModel)
        self.assertNotIn("confirmation", context)

    def test_server_generates_and_returns_a_session_id(self):
        self._install_llm(FakeChatModel(AIMessage(content="سلام")))
        first = self._post(self.token_a)
        self.assertEqual(first.status_code, 200)
        generated = first.json()["session_id"]
        self.assertTrue(generated)
        self.assertRegex(generated, r"^[A-Za-z0-9_-]{16,120}$")

        self._install_llm(FakeChatModel(AIMessage(content="دوباره سلام")))
        second = self._post(self.token_a, session_id=generated)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["session_id"], generated)

    def test_first_write_request_persists_hashed_pending_action(self):
        self.appointment_id = _create_appointment()
        model = FakeChatModel(
            _cancel_call(self.appointment_id, call_id="call-first")
        )
        response, token = self._issue_write(
            self.token_a, "sess-first", self.appointment_id, model
        )

        self.assertEqual(response.json()["session_id"], "sess-first")
        self.assertEqual(_appointment_status(self.appointment_id), "scheduled")
        self.assertEqual(model.calls, 1)

        row = _confirmation_row(self.user_a.id, "sess-first")
        self.assertIsNotNone(row)
        self.assertEqual(row["tool_name"], "cancel_appointment")
        self.assertEqual(row["arguments"], {"appointment_id": self.appointment_id})
        self.assertEqual(row["tool_call_id"], "call-first")
        self.assertNotEqual(row["token_hash"], token)
        self.assertEqual(len(row["token_hash"]), 64)
        self.assertNotIn(token, row["token_hash"])
        self.assertIsNone(row["consumed_at"])
        self.assertIsNone(row["decision"])
        self.assertLess(row["created_at"], row["expires_at"])

    def test_approval_in_second_request_executes_exactly_once(self):
        self.appointment_id = _create_appointment()
        model = FakeChatModel(
            _cancel_call(self.appointment_id),
            AIMessage(content="نوبت لغو شد."),
        )
        _, token = self._issue_write(
            self.token_a, "sess-approve", self.appointment_id, model
        )

        approved = self._approve(self.token_a, "sess-approve", token)
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()["reply"], "نوبت لغو شد.")
        self.assertFalse(approved.json()["confirmation_required"])
        self.assertEqual(_appointment_status(self.appointment_id), "cancelled")

        row = _confirmation_row(self.user_a.id, "sess-approve")
        self.assertIsNotNone(row["consumed_at"])
        self.assertEqual(row["decision"], "approved")
        self.assertEqual(model.calls, 2)

    def test_replayed_token_is_rejected_without_executing_again(self):
        self.appointment_id = _create_appointment()
        model = FakeChatModel(
            _cancel_call(self.appointment_id),
            AIMessage(content="نوبت لغو شد."),
        )
        _, token = self._issue_write(
            self.token_a, "sess-replay", self.appointment_id, model
        )
        first = self._approve(self.token_a, "sess-replay", token)
        self.assertEqual(first.status_code, 200)
        calls_after_first = model.calls

        replay = self._approve(self.token_a, "sess-replay", token)
        self.assertEqual(replay.status_code, 409)
        self.assertEqual(
            replay.json()["error"]["code"], "AGENT_CONFIRMATION_INVALID"
        )
        self.assertEqual(model.calls, calls_after_first)
        self.assertEqual(_appointment_status(self.appointment_id), "cancelled")

    def test_foreign_user_cannot_consume_another_users_token(self):
        self.appointment_id = _create_appointment()
        model = FakeChatModel(
            _cancel_call(self.appointment_id),
            AIMessage(content="نوبت لغو شد."),
        )
        _, token = self._issue_write(
            self.token_a, "sess-victim", self.appointment_id, model
        )

        foreign = self._approve(self.token_b, "sess-victim", token)
        self.assertEqual(foreign.status_code, 409)
        self.assertEqual(
            foreign.json()["error"]["code"], "AGENT_CONFIRMATION_INVALID"
        )
        self.assertEqual(model.calls, 1)
        self.assertEqual(_appointment_status(self.appointment_id), "scheduled")

        row = _confirmation_row(self.user_a.id, "sess-victim")
        self.assertIsNone(row["consumed_at"])

        owner = self._approve(self.token_a, "sess-victim", token)
        self.assertEqual(owner.status_code, 200, owner.text)
        self.assertEqual(_appointment_status(self.appointment_id), "cancelled")

    def test_same_user_with_a_different_session_is_rejected(self):
        self.appointment_id = _create_appointment()
        model = FakeChatModel(
            _cancel_call(self.appointment_id),
            AIMessage(content="نوبت لغو شد."),
        )
        _, token = self._issue_write(
            self.token_a, "sess-one", self.appointment_id, model
        )

        other_session = self._approve(self.token_a, "sess-two", token)
        self.assertEqual(other_session.status_code, 409)
        self.assertEqual(model.calls, 1)
        self.assertEqual(_appointment_status(self.appointment_id), "scheduled")

        owner = self._approve(self.token_a, "sess-one", token)
        self.assertEqual(owner.status_code, 200, owner.text)
        self.assertEqual(_appointment_status(self.appointment_id), "cancelled")

    def test_expired_token_is_rejected_without_execution(self):
        self.appointment_id = _create_appointment()
        model = FakeChatModel(_cancel_call(self.appointment_id))
        _, token = self._issue_write(
            self.token_a, "sess-expired", self.appointment_id, model
        )
        row = _confirmation_row(self.user_a.id, "sess-expired")
        self.assertIsNotNone(row)

        future = row["expires_at"] + timedelta(seconds=1)
        with patch.object(
            confirmations_module, "_utcnow", return_value=future
        ):
            response = self._approve(
                self.token_a, "sess-expired", token
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["error"]["code"], "AGENT_CONFIRMATION_INVALID"
        )
        self.assertEqual(model.calls, 1)
        self.assertEqual(_appointment_status(self.appointment_id), "scheduled")
        self.assertIsNone(
            _confirmation_row(self.user_a.id, "sess-expired")["consumed_at"]
        )

    def test_confirmation_without_session_id_is_rejected(self):
        self.appointment_id = _create_appointment()
        model = FakeChatModel(
            _cancel_call(self.appointment_id),
            AIMessage(content="نوبت لغو شد."),
        )
        _, token = self._issue_write(
            self.token_a, "sess-missing", self.appointment_id, model
        )

        response = self._post(
            self.token_a,
            message="تأیید می‌کنم",
            confirmation={"token": token, "decision": "approved"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["error"]["code"], "AGENT_CONFIRMATION_INVALID"
        )
        self.assertEqual(model.calls, 1)
        self.assertEqual(_appointment_status(self.appointment_id), "scheduled")

        # The owner can still approve with the original session id.
        owner = self._approve(self.token_a, "sess-missing", token)
        self.assertEqual(owner.status_code, 200, owner.text)

    def test_rejected_confirmation_is_consumed_but_does_not_execute(self):
        self.appointment_id = _create_appointment()
        model = FakeChatModel(_cancel_call(self.appointment_id))
        _, token = self._issue_write(
            self.token_a, "sess-reject", self.appointment_id, model
        )

        rejected = self._approve(
            self.token_a, "sess-reject", token, decision="rejected"
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(rejected.json()["reply"], "درخواست انجام نشد.")
        self.assertFalse(rejected.json()["confirmation_required"])
        self.assertEqual(model.calls, 1)
        self.assertEqual(_appointment_status(self.appointment_id), "scheduled")

        row = _confirmation_row(self.user_a.id, "sess-reject")
        self.assertIsNotNone(row["consumed_at"])
        self.assertEqual(row["decision"], "rejected")

        replay = self._approve(self.token_a, "sess-reject", token)
        self.assertEqual(replay.status_code, 409)

    def test_new_write_in_same_session_invalidates_old_token(self):
        self.appointment_id = _create_appointment()
        model = FakeChatModel(
            _cancel_call(self.appointment_id, call_id="call-old"),
            _cancel_call(self.appointment_id, call_id="call-new"),
        )
        _, old_token = self._issue_write(
            self.token_a, "sess-renew", self.appointment_id, model
        )
        old_hash = _confirmation_row(self.user_a.id, "sess-renew")["token_hash"]

        self._install_llm(model)
        second = self._post(
            self.token_a,
            message="دوباره لغو کن",
            session_id="sess-renew",
        )
        self.assertEqual(second.status_code, 200, second.text)
        new_token = second.json()["confirmation_token"]
        self.assertTrue(new_token)
        self.assertNotEqual(old_token, new_token)

        row = _confirmation_row(self.user_a.id, "sess-renew")
        self.assertNotEqual(row["token_hash"], old_hash)
        self.assertIsNone(row["consumed_at"])

        old_attempt = self._approve(self.token_a, "sess-renew", old_token)
        self.assertEqual(old_attempt.status_code, 409)
        self.assertEqual(model.calls, 2)
        self.assertEqual(_appointment_status(self.appointment_id), "scheduled")

    def test_tool_failure_after_consume_burns_the_token(self):
        missing_id = 9999999
        model = FakeChatModel(
            _cancel_call(missing_id, call_id="call-fail"),
            AIMessage(content="نوبت پیدا نشد."),
        )
        _, token = self._issue_write(
            self.token_a, "sess-fail", missing_id, model
        )

        failed = self._approve(self.token_a, "sess-fail", token)
        self.assertEqual(failed.status_code, 200, failed.text)
        self.assertEqual(failed.json()["reply"], "نوبت پیدا نشد.")
        self.assertEqual(model.calls, 2)

        row = _confirmation_row(self.user_a.id, "sess-fail")
        self.assertIsNotNone(row["consumed_at"])
        self.assertEqual(row["decision"], "approved")

        replay = self._approve(self.token_a, "sess-fail", token)
        self.assertEqual(replay.status_code, 409)
        self.assertEqual(model.calls, 2)


if __name__ == "__main__":
    unittest.main()
