"""Characterization tests for the decision node's less-travelled branches.

They pin the behaviour of ``_agent_decision_impl`` so the function can be
restructured safely. Each test drives the compiled graph end to end with a
fake chat model and an in-memory database.
"""

import unittest
from types import SimpleNamespace

from langchain_core.messages import AIMessage
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agent import agent_graph, create_initial_state
from app.models.base import Base
from app.models.user import User


class _FakeModel:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def bind_tools(self, _schemas):
        return self

    async def ainvoke(self, _messages):
        self.calls += 1
        return self.responses.pop(0)


def _tool_call(name, args, call_id="call-1"):
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


class DecisionBranchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.session_factory() as db:
            admin = User(
                full_name="مدیر آزمون",
                phone="09100000001",
                password_hash="x",
                role="admin",
                is_active=True,
            )
            db.add(admin)
            await db.commit()
            await db.refresh(admin)
            self.admin_id = admin.id

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def _run(self, model, **state_kwargs):
        async with self.session_factory() as db:
            admin = await db.get(User, self.admin_id)
            state = create_initial_state(
                messages=[{"role": "user", "content": "سلام"}], **state_kwargs
            )
            return await agent_graph.ainvoke(
                state,
                context={
                    "db": db,
                    "llm": model,
                    "session_id": "session-test",
                    "actor": admin,
                },
            )

    async def test_non_dict_pending_action_is_rejected_without_execution(self):
        model = _FakeModel()
        async with self.session_factory() as db:
            admin = await db.get(User, self.admin_id)
            state = create_initial_state(
                messages=[{"role": "user", "content": "تایید"}]
            )
            state["pending_action"] = "not-a-dict"
            result = await agent_graph.ainvoke(
                state,
                context={"db": db, "llm": model, "session_id": "s", "actor": admin},
            )
        self.assertEqual(model.calls, 0)
        self.assertTrue(result["final_response"])
        self.assertFalse(result.get("confirmation_required"))

    async def test_host_requested_read_tool_runs_then_model_answers(self):
        model = _FakeModel(AIMessage(content="خدمات را دیدم."))
        result = await self._run(
            model,
            requested_tool="search_dental_services",
            tool_arguments={},
        )
        self.assertEqual(model.calls, 1)
        self.assertEqual(result["final_response"], "خدمات را دیدم.")
        roles = [message["role"] for message in result["messages"]]
        self.assertIn("tool", roles)
        self.assertTrue(result["last_tool_result"]["ok"])

    async def test_invalid_model_arguments_become_validation_error(self):
        model = _FakeModel(
            _tool_call("book_appointment", {}),
            AIMessage(content="اطلاعات ناقص است."),
        )
        result = await self._run(model)
        self.assertEqual(result["last_tool_error"].code, "COMMON_VALIDATION_ERROR")
        self.assertFalse(result.get("confirmation_required"))
        self.assertEqual(result["final_response"], "اطلاعات ناقص است.")
        self.assertEqual(model.calls, 2)

    async def test_malformed_model_tool_call_is_dropped(self):
        broken = SimpleNamespace(
            content="", tool_calls=[{"name": 5, "args": "x", "id": "bad"}]
        )
        result = await self._run(_FakeModel(broken))
        self.assertEqual(
            result["final_response"], "متوجه درخواست نشدم؛ لطفاً آن را واضح‌تر بیان کنید."
        )
        self.assertFalse(result.get("last_tool_result"))

    async def test_empty_model_reply_uses_fallback_text(self):
        result = await self._run(_FakeModel(AIMessage(content="")))
        self.assertEqual(
            result["final_response"], "متوجه درخواست نشدم؛ لطفاً آن را واضح‌تر بیان کنید."
        )


if __name__ == "__main__":
    unittest.main()
