"""Server-side patient binding for patient-bound tool calls."""

import logging
from typing import Any

from langgraph.runtime import Runtime
from sqlalchemy import inspect as sa_inspect

from app.agent.context import AgentContext
from app.agent.outcomes import _catalog_error
from app.agent.registry import (
    PATIENT_BOUND_FIELDS,
    PATIENT_ID_INJECTED_TOOLS,
)
from app.agent_tools.schemas import AgentToolError
from app.auth.permissions import (
    actor_role,
    authorize_tool_call,
    linked_patient_ids,
)
from app.errors import AppError
from app.models.user import User

logger = logging.getLogger("dental_agent.agent")


async def _stable_actor(runtime: Runtime[AgentContext]) -> User | None:
    """Return the trusted actor, refreshing it only when the ORM expired it.

    A failed write rolls the session back, which expires every loaded ORM
    instance. Reading ``actor.id``/``actor.role`` afterwards could trigger a
    lazy load outside the async/greenlet context (``MissingGreenlet``). Test
    doubles that are transient/detached keep their in-memory attributes.
    """
    actor = runtime.context.get("actor")
    db = runtime.context.get("db")
    if actor is None or db is None:
        return None
    try:
        state = sa_inspect(actor)
        if state.persistent and state.expired:
            await db.refresh(actor)
    except Exception:
        logger.warning("Agent actor could not be refreshed; failing closed")
        return None
    return actor


def _is_patient_actor(actor: User | None) -> bool:
    return actor is not None and actor_role(actor) == "patient"


async def _prepare_patient_call(
    runtime: Runtime[AgentContext],
    call: dict[str, Any],
    actor: User | None,
) -> tuple[dict[str, Any], AgentToolError | None]:
    """Remove model-supplied identity/internal ids for patient-role calls.

    For tools that take a patient id, the selected record is injected from
    the authenticated account. When the account owns several records and no
    patient has been chosen yet, booking tools fail with a deterministic
    ``PATIENT_SELECTION_REQUIRED`` so the host can render the patient cards
    instead of letting the model guess. For cancel/reschedule the target id is
    removed entirely; the confirmation gate resolves it from database facts.
    Staff callers are unaffected. Authorization still re-checks ownership.
    """
    if not _is_patient_actor(actor):
        return call, None

    name = call.get("tool_name")
    hidden = PATIENT_BOUND_FIELDS.get(name or "")
    if not hidden:
        return call, None

    linked = await linked_patient_ids(runtime.context["db"], actor)
    if not linked:
        return call, _catalog_error("PATIENT_ACCOUNT_NOT_LINKED")

    selected = runtime.context.get("selected_patient_id")
    if selected not in linked:
        selected = linked[0] if len(linked) == 1 else None
    if selected is None and name in PATIENT_ID_INJECTED_TOOLS:
        return call, _catalog_error("PATIENT_SELECTION_REQUIRED")

    arguments = dict(call.get("arguments") or {})
    if name in {"cancel_appointment", "reschedule_appointment"}:
        # A patient model may still try to name an internal row id. Reject a
        # foreign id explicitly before discarding it, so an attempt to touch
        # another patient's appointment is never silently retargeted.
        if arguments.get("appointment_id") is not None:
            try:
                await authorize_tool_call(
                    runtime.context["db"], actor, name, arguments
                )
            except AppError as exc:
                return call, _catalog_error(exc.code)
    bound = {
        key: value for key, value in arguments.items() if key not in hidden
    }
    if name in PATIENT_ID_INJECTED_TOOLS:
        bound["patient_id"] = selected
    return {**call, "arguments": bound}, None
