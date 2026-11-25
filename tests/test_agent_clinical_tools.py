"""Clinical agent tools: summary read and doctor-only plan drafts.

Covers ``get_patient_clinical_summary`` (staff/doctor read over the clinical
models) and ``create_treatment_plan_draft`` (doctor-only write that must go
through the graph's one-time confirmation and may only ever create rows in
``draft`` status). Handler tests follow ``test_agent_new_tools.py``; the
confirmation-flow tests follow ``test_agent_graph.py``.
"""

import os
import unittest
from datetime import datetime

os.environ.setdefault(
    "CONFIRMATION_HMAC_SECRET",
    "test-confirmation-hmac-secret-32-chars-long",
)

from langchain_core.messages import AIMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agent import agent_graph, create_initial_state
from app.agent.registry import TOOL_REGISTRY, get_llm_tool_schemas
from app.agent_tools import tools
from app.models.base import Base
from app.models.clinical_entry import ClinicalEntry
from app.models.patient import Patient
from app.models.prescription import Prescription
from app.models.tooth_status import ToothStatus
from app.models.treatment_plan import TreatmentPlanItem
from app.models.user import User
from app.models.doctor import Doctor


def _user(role: str, phone: str) -> User:
    return User(
        full_name=f"کاربر {role} {phone}",
        phone=phone,
        password_hash="unused",
        role=role,
        is_active=True,
    )


class FakeChatModel:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.received = []

    def bind_tools(self, tool_schemas):
        self.tool_schemas = list(tool_schemas)
        return self

    async def ainvoke(self, messages):
        self.received.append(list(messages))
        return self.responses.pop(0)


def _call(name, arguments, call_id="call-1"):
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": arguments, "id": call_id, "type": "tool_call"}
        ],
    )


class AgentClinicalToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False
        )
        self.db = self.session_factory()

        self.admin = _user("admin", "09940000001")
        self.receptionist = _user("receptionist", "09940000002")
        self.doctor_user = _user("doctor", "09940000003")
        self.patient_user = _user("patient", "09940000005")
        self.db.add_all(
            [self.admin, self.receptionist, self.doctor_user, self.patient_user]
        )
        await self.db.flush()

        self.patient = Patient(
            national_id="2000000142",
            full_name="بیمار بالینی",
            phone="09940000005",
            user_id=self.patient_user.id,
            is_account_holder=True,
        )
        self.other_patient = Patient(
            national_id="2000000143",
            full_name="بیمار دیگر",
            phone="09940000006",
        )
        self.doctor = Doctor(
            full_name="دکتر درمانگر",
            specialty="دندانپزشکی عمومی",
            phone="09940000007",
            user_id=self.doctor_user.id,
            is_active=True,
        )
        self.db.add_all([self.patient, self.other_patient, self.doctor])
        await self.db.flush()

        self.db.add_all(
            [
                ClinicalEntry(
                    patient_id=self.patient.id,
                    doctor_id=self.doctor.id,
                    kind="allergy",
                    title="حساسیت به پنی‌سیلین",
                    created_by_user_id=self.doctor_user.id,
                    created_at=datetime(2026, 10, 1, 9, 0),
                ),
                ClinicalEntry(
                    patient_id=self.patient.id,
                    doctor_id=self.doctor.id,
                    kind="treatment",
                    title="ترمیم دندان ۲۶",
                    tooth_fdi=26,
                    created_by_user_id=self.doctor_user.id,
                    created_at=datetime(2026, 10, 2, 9, 0),
                ),
                ToothStatus(
                    patient_id=self.patient.id,
                    tooth_fdi=26,
                    status="needs_treatment",
                    note="پوسیدگی عمیق",
                    updated_by_user_id=self.doctor_user.id,
                    updated_at=datetime(2026, 10, 2, 9, 0),
                ),
                ToothStatus(
                    patient_id=self.patient.id,
                    tooth_fdi=11,
                    status="healthy",
                    updated_by_user_id=self.doctor_user.id,
                    updated_at=datetime(2026, 10, 2, 9, 0),
                ),
                TreatmentPlanItem(
                    patient_id=self.patient.id,
                    doctor_id=self.doctor.id,
                    tooth_fdi=26,
                    title="عصب‌کشی و روکش دندان ۲۶",
                    status="planned",
                    created_by_user_id=self.doctor_user.id,
                    created_at=datetime(2026, 10, 2, 9, 0),
                    updated_at=datetime(2026, 10, 2, 9, 0),
                ),
                Prescription(
                    patient_id=self.patient.id,
                    doctor_id=self.doctor.id,
                    items=[
                        {"name": "آموکسی‌سیلین", "dose": "500mg"},
                        {"name": "ایبوپروفن", "dose": "400mg"},
                    ],
                    created_by_user_id=self.doctor_user.id,
                    created_at=datetime(2026, 10, 2, 10, 0),
                ),
            ]
        )
        await self.db.flush()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    # ------------------------------------------------------------------
    # get_patient_clinical_summary
    # ------------------------------------------------------------------

    async def test_clinical_summary_happy_path_for_staff_and_doctor(self):
        for actor in (self.admin, self.receptionist, self.doctor_user):
            result = await tools.get_patient_clinical_summary(
                self.db, self.patient.id, actor=actor
            )
            self.assertTrue(result.ok, actor.role)
            data = result.data
            self.assertEqual(data.full_name, "بیمار بالینی")
            self.assertEqual(data.allergies, ["حساسیت به پنی‌سیلین"])
            # Only the flagged tooth is listed; the healthy one is omitted.
            self.assertEqual(
                [tooth.tooth_fdi for tooth in data.flagged_teeth], [26]
            )
            self.assertEqual(data.flagged_teeth[0].status, "needs_treatment")
            self.assertEqual(len(data.open_plan_items), 1)
            self.assertEqual(data.open_plan_items[0].status, "planned")
            self.assertEqual(data.prescriptions_total, 1)
            self.assertEqual(
                data.latest_prescription.medication_names,
                ["آموکسی‌سیلین", "ایبوپروفن"],
            )
            # The national id never reaches the model-visible payload.
            self.assertNotIn("2000000142", result.model_dump_json())

    async def test_clinical_summary_denied_for_patient_even_for_own_record(self):
        own = await tools.get_patient_clinical_summary(
            self.db, self.patient.id, actor=self.patient_user
        )
        self.assertFalse(own.ok)
        self.assertEqual(own.error.code, "COMMON_FORBIDDEN")
        other = await tools.get_patient_clinical_summary(
            self.db, self.other_patient.id, actor=self.patient_user
        )
        self.assertFalse(other.ok)
        self.assertEqual(other.error.code, "COMMON_FORBIDDEN")

    async def test_clinical_summary_unknown_patient(self):
        result = await tools.get_patient_clinical_summary(
            self.db, 99999, actor=self.doctor_user
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "PATIENT_NOT_FOUND")

    # ------------------------------------------------------------------
    # create_treatment_plan_draft (handler level)
    # ------------------------------------------------------------------

    async def test_create_draft_happy_path_for_doctor(self):
        result = await tools.create_treatment_plan_draft(
            self.db,
            self.patient.id,
            "ترمیم دندان ۳۶",
            tooth_fdi=36,
            notes="پس از بررسی عکس",
            actor=self.doctor_user,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.data.status, "draft")
        self.assertEqual(result.data.tooth_fdi, 36)
        rows = (
            await self.db.execute(
                select(TreatmentPlanItem).where(
                    TreatmentPlanItem.patient_id == self.patient.id,
                    TreatmentPlanItem.status == "draft",
                )
            )
        ).scalars().all()
        self.assertEqual(len(rows), 1)
        # The treating doctor is resolved server-side from the account.
        self.assertEqual(rows[0].doctor_id, self.doctor.id)
        self.assertEqual(rows[0].title, "ترمیم دندان ۳۶")

    async def test_create_draft_denied_for_non_doctor_roles(self):
        # Doctor-only: even the administrator may not use the agent tool.
        for actor in (self.admin, self.receptionist, self.patient_user):
            result = await tools.create_treatment_plan_draft(
                self.db,
                self.patient.id,
                "ترمیم دندان ۳۶",
                actor=actor,
            )
            self.assertFalse(result.ok, actor.role)
            self.assertEqual(result.error.code, "COMMON_FORBIDDEN")
        drafts = (
            await self.db.execute(
                select(TreatmentPlanItem).where(
                    TreatmentPlanItem.status == "draft"
                )
            )
        ).scalars().all()
        self.assertEqual(drafts, [])

    async def test_create_draft_rejects_invalid_tooth(self):
        result = await tools.create_treatment_plan_draft(
            self.db,
            self.patient.id,
            "ترمیم دندان",
            tooth_fdi=99,
            actor=self.doctor_user,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "TOOTH_INVALID")

    async def test_create_draft_unlinked_doctor_fails_closed(self):
        unlinked = _user("doctor", "09940000009")
        self.db.add(unlinked)
        await self.db.flush()
        result = await tools.create_treatment_plan_draft(
            self.db,
            self.patient.id,
            "ترمیم دندان ۳۶",
            actor=unlinked,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "DOCTOR_ACCOUNT_NOT_LINKED")

    async def test_create_draft_respects_deny_override(self):
        self.doctor_user.permission_overrides = {"clinical:write": "deny"}
        result = await tools.create_treatment_plan_draft(
            self.db,
            self.patient.id,
            "ترمیم دندان ۳۶",
            actor=self.doctor_user,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "COMMON_FORBIDDEN")

    # ------------------------------------------------------------------
    # registry / visibility
    # ------------------------------------------------------------------

    def test_registry_shape_and_visibility(self):
        self.assertEqual(len(TOOL_REGISTRY), 23)
        self.assertEqual(
            TOOL_REGISTRY["get_patient_clinical_summary"].operation, "read"
        )
        self.assertEqual(
            TOOL_REGISTRY["create_treatment_plan_draft"].operation, "write"
        )
        doctor_names = [
            schema["function"]["name"]
            for schema in get_llm_tool_schemas(role="doctor")
        ]
        self.assertIn("create_treatment_plan_draft", doctor_names)
        for role in ("admin", "receptionist"):
            names = [
                schema["function"]["name"]
                for schema in get_llm_tool_schemas(role=role)
            ]
            self.assertIn("get_patient_clinical_summary", names)
            self.assertNotIn("create_treatment_plan_draft", names)
        patient_names = [
            schema["function"]["name"]
            for schema in get_llm_tool_schemas(patient_bound=True)
        ]
        self.assertNotIn("get_patient_clinical_summary", patient_names)
        self.assertNotIn("create_treatment_plan_draft", patient_names)

    # ------------------------------------------------------------------
    # confirmation flow through the graph
    # ------------------------------------------------------------------

    async def _invoke_graph(self, state, model, *, confirmation=None):
        async with self.session_factory() as db:
            doctor_user = await db.get(User, self.doctor_user.id)
            context = {
                "db": db,
                "llm": model,
                "now": datetime(2026, 10, 8, 8, 0),
                "actor": doctor_user,
                "session_id": "sess-clinical-1",
            }
            if confirmation is not None:
                context["confirmation"] = confirmation
            return await agent_graph.ainvoke(state, context=context)

    async def _draft_rows(self):
        async with self.session_factory() as db:
            rows = await db.execute(
                select(TreatmentPlanItem).where(
                    TreatmentPlanItem.status == "draft"
                )
            )
            return list(rows.scalars().all())

    async def test_draft_waits_for_confirmation_then_executes(self):
        model = FakeChatModel(
            _call(
                "create_treatment_plan_draft",
                {
                    "patient_id": self.patient.id,
                    "title": "روکش دندان ۲۶",
                    "tooth_fdi": 26,
                },
            ),
            AIMessage(content="پیش‌نویس ثبت شد."),
        )
        state = create_initial_state(
            messages=[
                {"role": "user", "content": "برای بیمار بالینی پیش‌نویس روکش بنویس"}
            ]
        )
        pending = await self._invoke_graph(state, model)
        self.assertTrue(pending["confirmation_required"])
        self.assertEqual(
            pending["pending_action"]["tool_name"],
            "create_treatment_plan_draft",
        )
        prompt = pending["confirmation_prompt"]
        self.assertIn("پیش‌نویس طرح درمان", prompt)
        self.assertIn("بیمار بالینی", prompt)
        # Nothing is written before the one-time confirmation is approved.
        self.assertEqual(await self._draft_rows(), [])

        result = await self._invoke_graph(
            pending,
            model,
            confirmation={
                "token": pending["confirmation_token"],
                "decision": "approved",
            },
        )
        self.assertTrue(result["last_tool_result"]["ok"])
        self.assertEqual(result["last_tool_result"]["data"]["status"], "draft")
        rows = await self._draft_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].title, "روکش دندان ۲۶")
        self.assertEqual(rows[0].doctor_id, self.doctor.id)


if __name__ == "__main__":
    unittest.main()
