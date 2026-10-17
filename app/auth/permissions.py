"""Explicit role and patient-ownership authorization policy.

This module is the single choke point for authorization decisions used by
both HTTP routers and the LangGraph agent tool layer. Identity always comes
from the authenticated server-side user object; never from client input or
LLM-supplied arguments.

Roles: ``admin`` (everything), ``receptionist`` (patient registration and
appointment management), ``doctor`` (read access to clinic records; no
writes), ``patient`` (only their own linked record and appointments).
Unknown or legacy roles get no permissions (fail-closed).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.models.appointment import Appointment
from app.models.patient import Patient
from app.models.user import User

ROLES: tuple[str, ...] = ("admin", "receptionist", "doctor", "patient")

# Coarse permission matrix: action -> roles allowed. Patient ownership is
# checked separately for patient-role actors owning only their linked record.
_ACTION_ROLES: dict[str, frozenset[str]] = {
    "patient:read": frozenset({"admin", "receptionist", "doctor"}),
    "patient:create": frozenset({"admin", "receptionist"}),
    "patient:update": frozenset({"admin", "receptionist"}),
    "patient:delete": frozenset({"admin"}),
    "patient:link": frozenset({"admin"}),
    "appointment:read": frozenset({"admin", "receptionist", "doctor"}),
    "appointment:create": frozenset({"admin", "receptionist"}),
    "appointment:cancel": frozenset({"admin", "receptionist"}),
    "appointment:reschedule": frozenset({"admin", "receptionist"}),
    "user:create": frozenset({"admin"}),
    "clinic:read": frozenset(ROLES),
}


def actor_role(actor: User | None) -> str | None:
    """Return the actor's role, or None for anonymous/inactive callers."""
    if actor is None or not getattr(actor, "is_active", False):
        return None
    return getattr(actor, "role", None)


def role_allows(actor: User | None, action: str) -> bool:
    """Coarse check: does the actor's role include the named action."""
    role = actor_role(actor)
    if role is None:
        return False
    return role in _ACTION_ROLES.get(action, frozenset())


def require_action(actor: User | None, action: str) -> None:
    """Fail closed with a catalogued error when the action is not allowed."""
    if not role_allows(actor, action):
        raise AppError("COMMON_FORBIDDEN")


def require_role_present(actor: User | None, *roles: str) -> None:
    """Fail closed unless the actor has one of the given roles."""
    role = actor_role(actor)
    if role not in roles:
        raise AppError("COMMON_FORBIDDEN")


async def linked_patient_id(db: AsyncSession, actor: User | None) -> int | None:
    """Return the patient record id linked to this user account, if any."""
    if actor is None or getattr(actor, "role", None) != "patient":
        return None
    result = await db.execute(select(Patient.id).where(Patient.user_id == actor.id))
    row = result.scalar_one_or_none()
    return int(row) if row is not None else None


async def ensure_patient_scope(
    db: AsyncSession,
    actor: User | None,
    patient_id: int | None,
    action: str,
) -> int | None:
    """Staff use the coarse matrix; patients are limited to their own record.

    Returns the resolved patient id for patient-role callers (None only
    remains valid for listing contexts). Raises AppError on any violation.
    """
    role = actor_role(actor)
    if role is None:
        raise AppError("COMMON_UNAUTHORIZED")
    if role == "patient":
        linked = await linked_patient_id(db, actor)
        if linked is None:
            raise AppError("PATIENT_ACCOUNT_NOT_LINKED")
        if patient_id is not None and int(patient_id) != linked:
            raise AppError("COMMON_FORBIDDEN")
        return linked
    require_action(actor, action)
    return patient_id


async def _patient_by_national_id(
    db: AsyncSession, national_id: str
) -> Patient | None:
    result = await db.execute(
        select(Patient).where(Patient.national_id == national_id)
    )
    return result.scalar_one_or_none()


def _as_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


async def ensure_appointment_access(
    db: AsyncSession,
    actor: User | None,
    appointment_id: int | None,
    action: str,
) -> Appointment:
    """Load an appointment and enforce coarse plus ownership rules for it.

    Staff use the role matrix; a patient-role actor may only touch
    appointments of their own linked record. Raises AppError on any
    violation.
    """
    appointment = (
        await db.get(Appointment, appointment_id)
        if isinstance(appointment_id, int)
        else None
    )
    if appointment is None:
        raise AppError("APPOINTMENT_NOT_FOUND")
    role = actor_role(actor)
    if role is None:
        raise AppError("COMMON_UNAUTHORIZED")
    if role == "patient":
        linked = await linked_patient_id(db, actor)
        if linked is None or int(appointment.patient_id) != linked:
            raise AppError("COMMON_FORBIDDEN")
        return appointment
    require_action(actor, action)
    return appointment


async def ensure_bookable_patient(
    db: AsyncSession,
    actor: User | None,
    patient_id: int | None,
    national_id: str | None,
) -> int:
    """Resolve which patient record a booking may target.

    Staff (admin/receptionist) keep the current behavior: an explicit
    patient id or the national-id lookup path. A patient-role actor may only
    book for their own linked record and may never create a new patient
    identity or reuse somebody else's national id.
    """
    role = actor_role(actor)
    if role is None:
        raise AppError("COMMON_UNAUTHORIZED")
    if role in ("admin", "receptionist"):
        require_action(actor, "appointment:create")
        resolved = _as_int(patient_id)
        if resolved is not None:
            return resolved
        if national_id:
            patient = await _patient_by_national_id(db, national_id)
            if patient is not None:
                return int(patient.id)
        raise AppError("COMMON_VALIDATION_ERROR")
    if role == "patient":
        linked = await linked_patient_id(db, actor)
        if linked is None:
            raise AppError("PATIENT_ACCOUNT_NOT_LINKED")
        resolved = _as_int(patient_id)
        if resolved is not None and resolved == linked:
            return linked
        if resolved is None and national_id:
            patient = await _patient_by_national_id(db, national_id)
            if patient is not None and int(patient.id) == linked:
                return linked
        raise AppError("COMMON_FORBIDDEN")
    raise AppError("COMMON_FORBIDDEN")


_TOOL_ACTIONS: dict[str, str] = {
    "search_dental_services": "clinic:read",
    "find_doctors_for_service": "clinic:read",
    "find_available_slots": "clinic:read",
    "get_patient_appointments": "appointment:read",
    "book_appointment": "appointment:create",
    "cancel_appointment": "appointment:cancel",
    "reschedule_appointment": "appointment:reschedule",
}


async def authorize_tool_call(
    db: AsyncSession,
    actor: User | None,
    tool_name: str,
    arguments: object,
) -> None:
    """Fail closed unless the actor may run this agent tool call.

    Raises AppError so the LangGraph tool node can convert the denial into a
    catalogued tool error without executing any handler.
    """
    if not isinstance(arguments, dict):
        raise AppError("COMMON_FORBIDDEN")
    action = _TOOL_ACTIONS.get(tool_name)
    if action is None:
        raise AppError("COMMON_FORBIDDEN")
    role = actor_role(actor)
    if role is None:
        raise AppError("COMMON_FORBIDDEN")
    if role == "patient" and action == "clinic:read":
        return
    if role != "patient":
        require_action(actor, action)
        return
    # Patient actors are bound to their own linked record only.
    if action == "appointment:read":
        wanted = _as_int(arguments.get("patient_id"))
        linked = await linked_patient_id(db, actor)
        if linked is None:
            raise AppError("PATIENT_ACCOUNT_NOT_LINKED")
        if wanted is None or wanted != linked:
            raise AppError("COMMON_FORBIDDEN")
        return
    if action == "appointment:create":
        await ensure_bookable_patient(
            db, actor, arguments.get("patient_id"), arguments.get("national_id")
        )
        return
    if action in ("appointment:cancel", "appointment:reschedule"):
        await ensure_appointment_access(
            db, actor, _as_int(arguments.get("appointment_id")), action
        )
        return
    raise AppError("COMMON_FORBIDDEN")
