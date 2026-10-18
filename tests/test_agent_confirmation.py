"""Repository tests for persisted agent confirmations.

These tests use a temporary SQLite file (never the real database) and a
controlled clock. They cover token hashing, user/session binding, expiry,
single-use consumption, replacement, concurrent consumption, and two
independent engines observing the same state.
"""

import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only-32-chars-long"
os.environ["CONFIRMATION_HMAC_SECRET"] = (
    "test-confirmation-hmac-secret-32-chars-long"
)

from langchain_core.messages import AIMessage  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    async_sessionmaker,
    create_async_engine,
)

from app.agent import agent_graph, create_initial_state  # noqa: E402
from app.agent import confirmations as confirmations_module  # noqa: E402
from app.agent.confirmations import confirmation_store  # noqa: E402
from app.models.agent_confirmation import AgentConfirmation  # noqa: E402
from app.models.appointment import Appointment  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.user import User  # noqa: E402

USER_ID = 42


class FakeChatModel:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def bind_tools(self, _tool_schemas):
        return self

    async def ainvoke(self, _messages):
        self.calls += 1
        return self.responses.pop(0)


def _url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


class ConfirmationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "confirmations.db"
        self.engine = create_async_engine(
            _url(self.db_path), connect_args={"timeout": 10}
        )
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.factory()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()
        self.tempdir.cleanup()

    async def _issue(
        self,
        *,
        session_id="sess-1",
        user_id=USER_ID,
        tool_name="cancel_appointment",
        arguments=None,
        tool_call_id="call-1",
    ):
        return await confirmation_store.issue(
            self.db,
            session_id=session_id,
            user_id=user_id,
            tool_name=tool_name,
            arguments=arguments or {"appointment_id": 7},
            tool_call_id=tool_call_id,
        )

    async def test_issue_stores_only_the_hash_and_full_pending_action(self):
        record = await self._issue()
        self.assertTrue(record.token)
        self.assertGreaterEqual(len(record.token), 40)

        row = await self.db.get(AgentConfirmation, record.id)
        self.assertIsNotNone(row)
        self.assertEqual(row.user_id, USER_ID)
        self.assertEqual(row.session_id, "sess-1")
        self.assertEqual(row.tool_name, "cancel_appointment")
        self.assertEqual(row.arguments, {"appointment_id": 7})
        self.assertEqual(row.tool_call_id, "call-1")
        self.assertEqual(len(row.token_hash), 64)
        self.assertNotEqual(row.token_hash, record.token)
        self.assertNotIn(record.token, row.token_hash)
        self.assertIsNone(row.consumed_at)
        self.assertIsNone(row.decision)

    async def test_load_active_requires_user_session_and_token(self):
        record = await self._issue()

        loaded = await confirmation_store.load_active(
            self.db,
            record.token,
            session_id="sess-1",
            user_id=USER_ID,
        )
        self.assertIsNotNone(loaded)
        self.assertIsNone(loaded.token)  # raw token is never read back

        for kwargs in (
            {"session_id": "other", "user_id": USER_ID},
            {"session_id": "sess-1", "user_id": USER_ID + 1},
        ):
            self.assertIsNone(
                await confirmation_store.load_active(
                    self.db, record.token, **kwargs
                )
            )
        self.assertIsNone(
            await confirmation_store.load_active(
                self.db, "not-the-token", session_id="sess-1", user_id=USER_ID
            )
        )

    async def test_consume_is_single_use_and_records_decision(self):
        record = await self._issue()

        consumed = await confirmation_store.consume(
            self.db,
            record.token,
            session_id="sess-1",
            user_id=USER_ID,
            decision="approved",
        )
        self.assertIsNotNone(consumed)
        self.assertEqual(consumed.id, record.id)
        self.assertEqual(consumed.arguments, {"appointment_id": 7})

        second = await confirmation_store.consume(
            self.db,
            record.token,
            session_id="sess-1",
            user_id=USER_ID,
            decision="approved",
        )
        self.assertIsNone(second)

        row = await self.db.get(AgentConfirmation, record.id)
        self.assertIsNotNone(row.consumed_at)
        self.assertEqual(row.decision, "approved")
        self.assertIsNone(
            await confirmation_store.load_active(
                self.db,
                record.token,
                session_id="sess-1",
                user_id=USER_ID,
            )
        )

    async def test_expired_record_is_rejected_and_purged(self):
        record = await self._issue()
        future = record.expires_at + timedelta(seconds=1)

        with patch.object(
            confirmations_module, "_utcnow", return_value=future
        ):
            self.assertIsNone(
                await confirmation_store.load_active(
                    self.db,
                    record.token,
                    session_id="sess-1",
                    user_id=USER_ID,
                )
            )
            self.assertIsNone(
                await confirmation_store.consume(
                    self.db,
                    record.token,
                    session_id="sess-1",
                    user_id=USER_ID,
                    decision="approved",
                )
            )
            self.assertEqual(await confirmation_store.purge_expired(self.db), 1)

        result = await self.db.execute(select(AgentConfirmation))
        self.assertIsNone(result.scalar_one_or_none())

    async def test_new_issue_invalidates_previous_token_for_same_session(self):
        first = await self._issue(tool_call_id="call-old")
        second = await self._issue(tool_call_id="call-new")
        self.assertNotEqual(first.token, second.token)

        result = await self.db.execute(select(AgentConfirmation))
        rows = list(result.scalars().all())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].id, second.id)

        self.assertIsNone(
            await confirmation_store.consume(
                self.db,
                first.token,
                session_id="sess-1",
                user_id=USER_ID,
                decision="approved",
            )
        )
        self.assertIsNotNone(
            await confirmation_store.consume(
                self.db,
                second.token,
                session_id="sess-1",
                user_id=USER_ID,
                decision="approved",
            )
        )

    async def test_invalidate_removes_the_pending_record(self):
        record = await self._issue()
        await confirmation_store.invalidate(
            self.db, session_id="sess-1", user_id=USER_ID
        )
        self.assertIsNone(
            await confirmation_store.load_active(
                self.db,
                record.token,
                session_id="sess-1",
                user_id=USER_ID,
            )
        )

    async def test_missing_hmac_secret_fails_closed(self):
        with patch.dict(
            os.environ, {"CONFIRMATION_HMAC_SECRET": ""}, clear=False
        ):
            with self.assertRaises(RuntimeError):
                await self._issue()

    async def test_two_engines_share_state_and_cannot_consume_twice(self):
        record = await self._issue()
        second_engine = create_async_engine(
            _url(self.db_path), connect_args={"timeout": 10}
        )
        second_factory = async_sessionmaker(
            second_engine, expire_on_commit=False
        )
        try:
            async with second_factory() as second_db:
                loaded = await confirmation_store.load_active(
                    second_db,
                    record.token,
                    session_id="sess-1",
                    user_id=USER_ID,
                )
                self.assertIsNotNone(loaded)

                consumed = await confirmation_store.consume(
                    second_db,
                    record.token,
                    session_id="sess-1",
                    user_id=USER_ID,
                    decision="approved",
                )
                self.assertIsNotNone(consumed)

            self.assertIsNone(
                await confirmation_store.consume(
                    self.db,
                    record.token,
                    session_id="sess-1",
                    user_id=USER_ID,
                    decision="approved",
                )
            )
        finally:
            await second_engine.dispose()

    async def test_concurrent_consume_allows_exactly_one_winner(self):
        record = await self._issue()
        second_engine = create_async_engine(
            _url(self.db_path), connect_args={"timeout": 10}
        )
        second_factory = async_sessionmaker(
            second_engine, expire_on_commit=False
        )
        try:
            async with second_factory() as second_db:
                results = await asyncio.gather(
                    confirmation_store.consume(
                        self.db,
                        record.token,
                        session_id="sess-1",
                        user_id=USER_ID,
                        decision="approved",
                    ),
                    confirmation_store.consume(
                        second_db,
                        record.token,
                        session_id="sess-1",
                        user_id=USER_ID,
                        decision="approved",
                    ),
                )
            winners = [item for item in results if item is not None]
            self.assertEqual(len(winners), 1)
            self.assertEqual(winners[0].id, record.id)
        finally:
            await second_engine.dispose()

        row = await self.db.get(AgentConfirmation, record.id)
        self.assertIsNotNone(row.consumed_at)
        self.assertEqual(row.decision, "approved")

    async def test_concurrent_graph_approval_executes_tool_once(self):
        appointment = Appointment(
            patient_id=1,
            doctor_id=1,
            service_id=1,
            appointment_time=datetime(2030, 1, 1, 10, 0),
            status="scheduled",
        )
        self.db.add(appointment)
        await self.db.commit()
        await self.db.refresh(appointment)

        record = await self._issue(
            arguments={"appointment_id": appointment.id},
            tool_call_id="call-concurrent",
        )
        second_engine = create_async_engine(
            _url(self.db_path), connect_args={"timeout": 10}
        )
        second_factory = async_sessionmaker(
            second_engine, expire_on_commit=False
        )

        def _state():
            state = create_initial_state()
            state["pending_action"] = {
                "tool_name": record.tool_name,
                "arguments": dict(record.arguments),
                "tool_call_id": record.tool_call_id,
            }
            state["pending_tool_calls"] = [dict(state["pending_action"])]
            state["confirmation_status"] = "pending"
            return state

        def _context(db):
            return {
                "db": db,
                "llm": model,
                "session_id": "sess-1",
                "actor": User(
                    id=USER_ID,
                    full_name="Concurrent Probe",
                    phone="09900000222",
                    password_hash="unused",
                    role="receptionist",
                    is_active=True,
                ),
                "confirmation": {
                    "token": record.token,
                    "decision": "approved",
                },
            }

        model = FakeChatModel(AIMessage(content="نوبت لغو شد."))
        try:
            async with second_factory() as second_db:
                results = await asyncio.gather(
                    agent_graph.ainvoke(_state(), context=_context(self.db)),
                    agent_graph.ainvoke(_state(), context=_context(second_db)),
                )
        finally:
            await second_engine.dispose()

        winners = [
            result
            for result in results
            if result.get("last_tool_result")
            and result["last_tool_result"].get("ok")
        ]
        rejected = [
            result
            for result in results
            if result.get("final_response") == "درخواست انجام نشد."
        ]
        self.assertEqual(len(winners), 1)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(model.calls, 1)

        refreshed = await self.db.get(Appointment, appointment.id)
        await self.db.refresh(refreshed)
        self.assertEqual(refreshed.status, "cancelled")

        row = await self.db.get(AgentConfirmation, record.id)
        await self.db.refresh(row)
        self.assertIsNotNone(row.consumed_at)
        self.assertEqual(row.decision, "approved")


if __name__ == "__main__":
    unittest.main()
