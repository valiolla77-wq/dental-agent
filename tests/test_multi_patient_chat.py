"""Multi-patient account behavior in the agent chat endpoint."""

import asyncio
import os
import unittest
from unittest.mock import patch

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

from app.auth.security import create_access_token, hash_password  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.chat import (  # noqa: E402
    AgentConversation,
    AgentMessage,
)
from app.models.patient import Patient  # noqa: E402
from app.models.user import User  # noqa: E402
from app.routers import agent_chat as agent_chat_module  # noqa: E402
from app.routers.agent_chat import get_chat_llm  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class FakeChatModel:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def bind_tools(self, _schemas):
        return self

    async def ainvoke(self, _messages):
        self.calls += 1
        return self.responses.pop(0)


class SingleTurnGraph:
    def __init__(self, result):
        self.result = result
        self.calls = 0
        self.states = []
        self.contexts = []

    async def ainvoke(self, state, context=None, config=None):
        self.calls += 1
        self.states.append(state)
        self.contexts.append(context)
        return self.result


def _book_call():
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
                "id": "call-multi-book",
                "type": "tool_call",
            }
        ],
    )


class MultiPatientChatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _run(init_db())

    def setUp(self):
        self.client = TestClient(app)
        self.phone = "09360002101"
        self.holder_phone = "09360002102"
        self.family_phone = "09360002103"
        self._cleanup()
        self.user = _run(self._create_user())
        self.token = create_access_token(subject=str(self.user.id))
        self.holder = _run(
            self._create_patient(
                "علی صاحب حساب",
                self.holder_phone,
                "1000001101",
                holder=True,
            )
        )
        self.family = _run(
            self._create_patient(
                "مریم خانواده",
                self.family_phone,
                "1000001102",
                holder=False,
            )
        )

        # These tests replace the graph; the LLM dependency only has to exist.
        app.dependency_overrides[get_chat_llm] = lambda: object()

    def tearDown(self):
        app.dependency_overrides.pop(get_chat_llm, None)
        self._cleanup()

    async def _create_user(self):
        async with SessionLocal() as db:
            user = User(
                full_name="حساب چندپرونده",
                phone=self.phone,
                password_hash=hash_password("probe-pass-123"),
                role="patient",
                is_active=True,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            return user

    async def _create_patient(self, name, phone, national_id, *, holder):
        async with SessionLocal() as db:
            patient = Patient(
                full_name=name,
                phone=phone,
                national_id=national_id,
                user_id=self.user.id,
                is_account_holder=holder,
                record_status="complete",
            )
            db.add(patient)
            await db.commit()
            await db.refresh(patient)
            return patient

    def _cleanup(self):
        async def _remove():
            async with SessionLocal() as db:
                user = (
                    await db.execute(select(User).where(User.phone == self.phone))
                ).scalar_one_or_none()
                if user is not None:
                    conversations = (
                        await db.execute(
                            select(AgentConversation.id).where(
                                AgentConversation.user_id == user.id
                            )
                        )
                    ).scalars().all()
                    if conversations:
                        await db.execute(
                            delete(AgentMessage).where(
                                AgentMessage.conversation_id.in_(conversations)
                            )
                        )
                        await db.execute(
                            delete(AgentConversation).where(
                                AgentConversation.user_id == user.id
                            )
                        )
                    await db.execute(
                        delete(Patient).where(Patient.user_id == user.id)
                    )
                    await db.execute(delete(User).where(User.id == user.id))
                await db.commit()

        _run(_remove())

    def _chat(self, message, session_id):
        return self.client.post(
            "/agent/chat",
            json={"message": message, "session_id": session_id},
            headers={"Authorization": f"Bearer {self.token}"},
        )

    def _slot_options_graph(self):
        return SingleTurnGraph(
            {
                "final_response": "این زمان‌ها آزاد است:",
                "last_tool_name": "find_available_slots",
                "last_tool_result": {
                    "ok": True,
                    "data": {
                        "doctor_id": 7,
                        "service_id": 3,
                        "appointment_date": "1405/08/25",
                        "available_slots": ["10:00", "11:30"],
                    },
                },
            }
        )

    def test_slot_selection_asks_which_saved_patient_then_books_deterministically(self):
        first = self._slot_options_graph()
        with patch.object(agent_chat_module, "agent_graph", first):
            response = self._chat("زمان‌های آزاد", "multi-session")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["options"][0]["kind"], "slot_time")

        capture = SingleTurnGraph({"final_response": "ثبت شد."})
        with patch.object(agent_chat_module, "agent_graph", capture):
            ask = self._chat("1", "multi-session")
        self.assertEqual(ask.status_code, 200, ask.text)
        body = ask.json()
        self.assertEqual(body["reply"], "برای کدام بیمار این نوبت ثبت شود؟")
        self.assertEqual(
            [option["kind"] for option in body["options"]], ["patient", "patient"]
        )
        self.assertEqual(
            [option["patient_id"] for option in body["options"]],
            [self.holder.id, self.family.id],
        )
        self.assertTrue(body["options"][0]["is_account_holder"])
        self.assertEqual(capture.calls, 0)

        with patch.object(agent_chat_module, "agent_graph", capture):
            chosen = self._chat("2", "multi-session")
        self.assertEqual(chosen.status_code, 200, chosen.text)
        self.assertEqual(capture.calls, 1)
        state = capture.states[0]
        self.assertEqual(state["requested_tool"], "book_appointment")
        self.assertEqual(
            state["tool_arguments"],
            {
                "patient_id": self.family.id,
                "doctor_id": 7,
                "service_id": 3,
                "appointment_date": "1405/08/25",
                "appointment_time": "10:00",
            },
        )
        self.assertEqual(capture.contexts[0]["selected_patient_id"], self.family.id)

    def test_booking_attempt_without_patient_choice_returns_patient_cards(self):
        model = FakeChatModel(
            _book_call(),
            AIMessage(content="برای کدام بیمار؟"),
        )
        app.dependency_overrides[get_chat_llm] = lambda: model
        response = self.client.post(
            "/agent/chat",
            json={"message": "یک نوبت رزرو کن", "session_id": "natural-booking"},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(
            body["reply"],
            "این درخواست برای کدام بیمار از پرونده‌های حساب شما انجام شود؟",
        )
        self.assertEqual(len(body["options"]), 2)
        self.assertTrue(all(option["kind"] == "patient" for option in body["options"]))
        self.assertFalse(body["confirmation_required"])

    def test_new_conversation_has_no_saved_patient_selection(self):
        first = self._slot_options_graph()
        with patch.object(agent_chat_module, "agent_graph", first):
            self._chat("زمان‌های آزاد", "conversation-one")
        with patch.object(agent_chat_module, "agent_graph", SingleTurnGraph({"final_response": "x"})):
            self._chat("2", "conversation-one")

        capture = SingleTurnGraph({"final_response": "سلام"})
        with patch.object(agent_chat_module, "agent_graph", capture):
            self._chat("سلام", "conversation-two")
        self.assertIsNone(capture.contexts[0]["selected_patient_id"])


if __name__ == "__main__":
    unittest.main()
