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
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.user import User

ROLES: tuple[str, ...] = ("admin", "receptionist", "doctor", "patient")

# A patient account is deliberately read/booking-only: it may view its own
# record and appointments and use the self-service appointment tools, but it
# may not edit demographic data, create patient records, or link accounts.
_PATIENT_RECORD_ACTIONS = frozenset({"patient:read", "appointment:read"})
_PATIENT_APPOINTMENT_ACTIONS = frozenset(
    {"appointment:read", "appointment:cancel", "appointment:reschedule"}
)

# Coarse permission matrix: action -> roles allowed. Patient ownership is
# checked separately for patient-role actors owning only their linked record.
_ACTION_ROLES: dict[str, frozenset[str]] = {
    "patient:read": frozenset({"admin", "receptionist", "doctor"}),
    "patient:create": frozenset({"admin", "receptionist"}),
    "patient:update": frozenset({"admin", "receptionist"}),
    "patient:delete": frozenset({"admin"}),
    "patient:link": frozenset({"admin"}),
    # Front-desk style lookup (name/phone/national id fragment). Doctors and
    # receptionists look records up for walk-ins and phone calls; the agent
    # tool masks national ids in its output either way.
    "patient:search": frozenset({"admin", "receptionist", "doctor"}),
    "appointment:read": frozenset({"admin", "receptionist", "doctor"}),
    "appointment:create": frozenset({"admin", "receptionist"}),
    "appointment:cancel": frozenset({"admin", "receptionist"}),
    "appointment:reschedule": frozenset({"admin", "receptionist"}),
    # Daily patient journey: check-in, start and completion are performed by
    # the front desk and the treating doctor (single-clinic workflow).
    "appointment:flow": frozenset({"admin", "receptionist", "doctor"}),
    "user:create": frozenset({"admin"}),
    # Chat-level staff directory: administrators may review accounts through
    # the agent; account writes stay with the dedicated HTTP endpoints.
    "user:read": frozenset({"admin"}),
    # Append-only audit trail review through the agent (admin duty).
    "audit:read": frozenset({"admin"}),
    # Every authenticated role may file an error report or suggestion.
    "feedback:create": frozenset(ROLES),
    "clinic:read": frozenset(ROLES),
    # Clinic-wide reports: only roles that may already see all appointments
    # get the workload summary; only administer the whole-clinic overview.
    "report:appointments": frozenset({"admin", "receptionist", "doctor"}),
    "report:overview": frozenset({"admin"}),
    # Feedback inbox review stays an administrator duty.
    "report:feedback": frozenset({"admin"}),
    # Clinical record: the treating team reads it; only clinicians (and the
    # administrator) write treatment notes, allergy alerts and tooth-chart
    # statuses. Reception stays read-only by design.
    "clinical:read": frozenset({"admin", "receptionist", "doctor"}),
    "clinical:write": frozenset({"admin", "doctor"}),
    # Post-visit satisfaction rating is a patient-only self-service action.
    "visit_rating:create": frozenset({"patient"}),
}

# Stable, ordered catalog of every overridable action (admin UI matrix).
PERMISSION_ACTIONS: tuple[str, ...] = tuple(_ACTION_ROLES.keys())

# Effects an admin may pin for one staff account on top of the role matrix.
PERMISSION_EFFECTS: tuple[str, ...] = ("allow", "deny")


def action_default_roles(action: str) -> frozenset[str]:
    """Roles that get the action by default (read-only catalog helper)."""
    return _ACTION_ROLES.get(action, frozenset())


def _override_effect(user: User | None, action: str) -> str | None:
    """Return this account's pinned effect for an action, if applicable.

    Overrides are a staff-management tool: they never apply to ``patient``
    accounts (ownership rules stay in control) and never to ``admin``
    accounts (an administrator always keeps full reach so the clinic can
    never be locked out of its own system).
    """
    if user is None:
        return None
    if getattr(user, "role", None) not in ("receptionist", "doctor"):
        return None
    effect = user.overrides_dict().get(action)
    return effect if effect in PERMISSION_EFFECTS else None


def effective_permissions(user: User | None) -> list[dict[str, object]]:
    """Full per-action view used by the admin permission matrix.

    For every catalogued action it reports the role default, the account's
    pinned override (if any) and the final effective outcome.
    """
    role = actor_role(user)
    overrides = user.overrides_dict() if user is not None else {}
    actions: list[dict[str, object]] = []
    for action in PERMISSION_ACTIONS:
        default = role is not None and role in _ACTION_ROLES.get(action, frozenset())
        pinned = overrides.get(action)
        if pinned not in PERMISSION_EFFECTS:
            pinned = None
        if pinned == "allow":
            effective = True
        elif pinned == "deny":
            effective = False
        else:
            effective = default
        actions.append(
            {
                "action": action,
                "role_default": default,
                "override": pinned,
                "effective": effective,
            }
        )
    return actions


def actor_role(actor: User | None) -> str | None:
    """Return the actor's role, or None for anonymous/inactive callers."""
    if actor is None or not getattr(actor, "is_active", False):
        return None
    return getattr(actor, "role", None)


def role_allows(actor: User | None, action: str) -> bool:
    """Coarse check: does the actor's role include the named action.

    A per-account override (``allow``/``deny``) always wins for staff roles;
    patients and admins are evaluated purely by the role matrix.
    """
    role = actor_role(actor)
    if role is None:
        return False
    effect = _override_effect(actor, action)
    if effect == "allow":
        return True
    if effect == "deny":
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


async def linked_patient_ids(
    db: AsyncSession,
    actor: User | None,
) -> list[int]:
    """Return every patient record owned by this patient account, primary first."""
    if actor is None or getattr(actor, "role", None) != "patient":
        return []
    result = await db.execute(
        select(Patient.id)
        .where(Patient.user_id == actor.id)
        .order_by(Patient.is_account_holder.desc(), Patient.id)
    )
    return [int(row) for row in result.scalars().all()]


async def linked_patient_id(db: AsyncSession, actor: User | None) -> int | None:
    """Return the primary patient record id linked to this account, if any."""
    linked = await linked_patient_ids(db, actor)
    return linked[0] if linked else None


async def linked_doctor_id(db: AsyncSession, actor: User | None) -> int | None:
    """Return the doctor record id linked to this doctor account, if any."""
    if actor is None or getattr(actor, "role", None) != "doctor":
        return None
    result = await db.execute(select(Doctor.id).where(Doctor.user_id == actor.id))
    row = result.scalar_one_or_none()
    return int(row) if row is not None else None


async def ensure_doctor_listing_scope(
    db: AsyncSession,
    actor: User | None,
    requested_doctor_id: int | None,
) -> int | None:
    """Scope appointment listings to what the actor is allowed to see.

    Admin/receptionist may list everything or filter by any doctor. A doctor
    account is always scoped to its own linked record; it can never list more
    by supplying ids or bypass them by omitting the filter. Patients use the
    dedicated self-listing endpoint instead. Returns the effective
    ``doctor_id`` filter (``None`` only for admin/receptionist).
    """
    role = actor_role(actor)
    if role is None:
        raise AppError("COMMON_UNAUTHORIZED")
    if role == "patient":
        raise AppError("COMMON_FORBIDDEN")
    require_action(actor, "appointment:read")
    if role in ("admin", "receptionist"):
        return requested_doctor_id
    linked = await linked_doctor_id(db, actor)
    if linked is None:
        raise AppError("DOCTOR_ACCOUNT_NOT_LINKED")
    if requested_doctor_id is not None and int(requested_doctor_id) != linked:
        raise AppError("COMMON_FORBIDDEN")
    return linked


async def ensure_patient_scope(
    db: AsyncSession,
    actor: User | None,
    patient_id: int | None,
    action: str,
) -> int | None:
    """Staff use the coarse matrix; patients get read-only access to themselves.

    Patient accounts may view their own record and appointment list only.
    Demographic edits and account linking remain staff operations. Returns the
    resolved patient id for patient-role callers (None only remains valid for
    listing contexts). Raises AppError on any violation.
    """
    role = actor_role(actor)
    if role is None:
        raise AppError("COMMON_UNAUTHORIZED")
    if role == "patient":
        linked = await linked_patient_ids(db, actor)
        if not linked:
            raise AppError("PATIENT_ACCOUNT_NOT_LINKED")
        if action not in _PATIENT_RECORD_ACTIONS:
            raise AppError("COMMON_FORBIDDEN")
        if patient_id is not None and int(patient_id) not in linked:
            raise AppError("COMMON_FORBIDDEN")
        return int(patient_id) if patient_id is not None else linked[0]
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
        if action not in _PATIENT_APPOINTMENT_ACTIONS:
            raise AppError("COMMON_FORBIDDEN")
        linked = await linked_patient_ids(db, actor)
        if not linked or int(appointment.patient_id) not in linked:
            raise AppError("COMMON_FORBIDDEN")
        return appointment
    require_action(actor, action)
    return appointment


async def ensure_bookable_patient(
    db: AsyncSession,
    actor: User | None,
    patient_id: int | None,
    national_id: str | None,
    full_name: str | None = None,
    phone: str | None = None,
) -> int | None:
    """Resolve which patient record a booking may target.

    Staff (admin/receptionist) may use an explicit patient id, an existing
    national id, or the complete (national_id, full_name, phone) tuple for a
    new patient that ``create_booking`` will register atomically. A
    patient-role actor may only book for their own linked record and may never
    create a new patient identity or reuse somebody else's national id.
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
            if all(
                isinstance(value, str) and value.strip()
                for value in (full_name, phone)
            ):
                # No patient row exists yet; create_booking will create it.
                return None
        raise AppError("COMMON_VALIDATION_ERROR")
    if role == "patient":
        linked = await linked_patient_ids(db, actor)
        if not linked:
            raise AppError("PATIENT_ACCOUNT_NOT_LINKED")
        resolved = _as_int(patient_id)
        if resolved is not None and resolved in linked:
            return resolved
        if resolved is None and national_id:
            normalized = "".join(
                char for char in str(national_id) if char.isdigit()
            )
            patient = await _patient_by_national_id(db, normalized)
            if patient is not None and int(patient.id) in linked:
                return int(patient.id)
        if resolved is None and not national_id:
            # Legacy/manual callers may omit the id; the account-holder (or
            # oldest family record) remains the default only when unambiguous.
            if len(linked) == 1:
                return linked[0]
            raise AppError("PATIENT_SELECTION_REQUIRED")
        raise AppError("COMMON_FORBIDDEN")
    raise AppError("COMMON_FORBIDDEN")


_TOOL_ACTIONS: dict[str, str] = {
    "search_dental_services": "clinic:read",
    "find_doctors_for_service": "clinic:read",
    "find_available_slots": "clinic:read",
    "find_nearest_appointments": "clinic:read",
    "get_patient_appointments": "appointment:read",
    "book_appointment": "appointment:create",
    "cancel_appointment": "appointment:cancel",
    "reschedule_appointment": "appointment:reschedule",
    "get_clinic_appointments_report": "report:appointments",
    "get_clinic_overview_stats": "report:overview",
    "search_patients": "patient:search",
    "get_patient_summary": "patient:read",
    "get_doctor_schedules": "clinic:read",
    "get_doctor_day_plan": "appointment:read",
    "get_user_reports_summary": "report:feedback",
    # Role-scoped expansions: self-service profile for patients, staff
    # record management for the front desk, and administrator-only account
    # and audit reviews, plus a feedback channel open to every role.
    "get_my_profile": "patient:read",
    "create_patient": "patient:create",
    "update_patient": "patient:update",
    "get_staff_directory": "user:read",
    "get_audit_trail": "audit:read",
    "submit_feedback": "feedback:create",
}

# Tools that are meaningful only for patient-role sessions. They are hidden
# from staff sessions and fail closed when a staff identity reaches them.
_PATIENT_ONLY_TOOLS: frozenset[str] = frozenset({"get_my_profile"})

# Front-desk record management tools: patient-role callers are always
# rejected, staff callers go through the coarse matrix (where an override
# may grant a doctor record editing).
_STAFF_RECORD_TOOLS: frozenset[str] = frozenset(
    {"create_patient", "update_patient", "get_staff_directory", "get_audit_trail"}
)


def tool_action(tool_name: str) -> str | None:
    """Mapped permission action for an agent tool (None when unknown)."""
    return _TOOL_ACTIONS.get(tool_name)


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
    if tool_name in _PATIENT_ONLY_TOOLS:
        if role != "patient":
            raise AppError("COMMON_FORBIDDEN")
        return
    if tool_name in _STAFF_RECORD_TOOLS:
        if role == "patient":
            raise AppError("COMMON_FORBIDDEN")
        require_action(actor, action)
        return
    if tool_name == "get_doctor_day_plan":
        # Staff-only day agenda: doctor accounts are pinned to their own
        # linked record no matter what ids the model or host passes. The
        # generic patient ownership branch below would otherwise let a
        # patient through with an unset patient_id.
        if role == "patient":
            raise AppError("COMMON_FORBIDDEN")
        await ensure_doctor_listing_scope(
            db, actor, _as_int(arguments.get("doctor_id"))
        )
        return
    if tool_name == "submit_feedback":
        # Every authenticated role may file feedback; the handler scopes the
        # row to the acting account server-side.
        require_action(actor, action)
        return
    if role == "patient" and action == "clinic:read":
        return
    if role != "patient":
        require_action(actor, action)
        return
    # Patient actors can read any record owned by their own account only.
    if action == "appointment:read":
        wanted = _as_int(arguments.get("patient_id"))
        linked = await linked_patient_ids(db, actor)
        if not linked:
            raise AppError("PATIENT_ACCOUNT_NOT_LINKED")
        if wanted is not None and wanted not in linked:
            raise AppError("COMMON_FORBIDDEN")
        return
    if action == "appointment:create":
        await ensure_bookable_patient(
            db,
            actor,
            arguments.get("patient_id"),
            arguments.get("national_id"),
            arguments.get("full_name"),
            arguments.get("phone"),
        )
        return
    if action in ("appointment:cancel", "appointment:reschedule"):
        await ensure_appointment_access(
            db, actor, _as_int(arguments.get("appointment_id")), action
        )
        return
    raise AppError("COMMON_FORBIDDEN")
