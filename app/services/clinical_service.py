"""Clinical record service: entries and the per-tooth condition chart.

Authorization is performed by the router layer (``ensure_patient_scope``);
this module owns validation, persistence and the audit trail. Every write
appends one audit row inside the same transaction, mirroring the staff
management flow. A clinical write also drops one ``clinical_entry``
notification into the owning patient account's inbox so the portal banner
stays fresh without polling.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.models.appointment import Appointment
from app.models.clinical_entry import CLINICAL_ENTRY_KINDS, ClinicalEntry
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.prescription import Prescription
from app.models.tooth_status import TOOTH_STATUSES, ToothStatus, is_valid_tooth_fdi
from app.models.treatment_plan import (
    TREATMENT_PLAN_STATUSES,
    TreatmentPlanItem,
)
from app.models.user import User
from app.services import audit_service

logger = logging.getLogger(__name__)

TOOTH_FDI_MIN = 11
TOOTH_FDI_MAX = 48


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _validate_tooth_fdi(value: int | None) -> int | None:
    if value is None:
        return None
    if not is_valid_tooth_fdi(value):
        raise AppError("TOOTH_INVALID")
    return value


def _validate_kind(kind: str) -> str:
    if kind not in CLINICAL_ENTRY_KINDS:
        raise AppError("CLINICAL_ENTRY_INVALID")
    return kind


def _validate_status(status: str) -> str:
    if status not in TOOTH_STATUSES:
        raise AppError("TOOTH_STATUS_INVALID")
    return status


async def get_patient_clinical_view(
    db: AsyncSession,
    patient: Patient,
) -> dict[str, object]:
    """Entries (newest first) plus the sparse tooth chart for one record."""
    entry_rows = (
        await db.execute(
            select(ClinicalEntry, Doctor, User)
            .join(Doctor, ClinicalEntry.doctor_id == Doctor.id, isouter=True)
            .join(User, ClinicalEntry.created_by_user_id == User.id, isouter=True)
            .where(ClinicalEntry.patient_id == patient.id)
            .order_by(ClinicalEntry.created_at.desc(), ClinicalEntry.id.desc())
            .limit(300)
        )
    ).all()

    entries: list[dict[str, object]] = []
    for entry, doctor, author in entry_rows:
        entries.append(
            {
                "id": entry.id,
                "patient_id": entry.patient_id,
                "doctor_id": entry.doctor_id,
                "doctor_name": doctor.full_name if doctor else None,
                "appointment_id": entry.appointment_id,
                "kind": entry.kind,
                "tooth_fdi": entry.tooth_fdi,
                "title": entry.title,
                "body": entry.body,
                "created_by_name": author.full_name if author else None,
                "created_at": entry.created_at,
            }
        )

    teeth = (
        await db.execute(
            select(ToothStatus)
            .where(ToothStatus.patient_id == patient.id)
            .order_by(ToothStatus.tooth_fdi)
        )
    ).scalars().all()

    prescription_rows = (
        await db.execute(
            select(Prescription, Doctor, User)
            .join(Doctor, Prescription.doctor_id == Doctor.id, isouter=True)
            .join(
                User,
                Prescription.created_by_user_id == User.id,
                isouter=True,
            )
            .where(Prescription.patient_id == patient.id)
            .order_by(Prescription.created_at.desc(), Prescription.id.desc())
            .limit(100)
        )
    ).all()
    prescriptions = [
        {
            "id": prescription.id,
            "patient_id": prescription.patient_id,
            "doctor_id": prescription.doctor_id,
            "doctor_name": doctor.full_name if doctor else None,
            "appointment_id": prescription.appointment_id,
            "items": prescription.items or [],
            "notes": prescription.notes,
            "created_by_name": author.full_name if author else None,
            "created_at": prescription.created_at,
            "cancelled_at": prescription.cancelled_at,
        }
        for prescription, doctor, author in prescription_rows
    ]

    plan_rows = (
        await db.execute(
            select(TreatmentPlanItem, Doctor, User)
            .join(Doctor, TreatmentPlanItem.doctor_id == Doctor.id, isouter=True)
            .join(
                User,
                TreatmentPlanItem.created_by_user_id == User.id,
                isouter=True,
            )
            .where(TreatmentPlanItem.patient_id == patient.id)
            .order_by(
                TreatmentPlanItem.status.asc(),
                TreatmentPlanItem.created_at.asc(),
                TreatmentPlanItem.id.asc(),
            )
            .limit(200)
        )
    ).all()
    plan_items = [
        {
            "id": item.id,
            "patient_id": item.patient_id,
            "doctor_id": item.doctor_id,
            "doctor_name": doctor.full_name if doctor else None,
            "tooth_fdi": item.tooth_fdi,
            "title": item.title,
            "status": item.status,
            "notes": item.notes,
            "created_by_name": author.full_name if author else None,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }
        for item, doctor, author in plan_rows
    ]

    return {
        "patient": {
            "id": patient.id,
            "full_name": patient.full_name,
            "national_id": patient.national_id,
            "phone": patient.phone,
            "is_account_holder": patient.is_account_holder,
            "record_status": patient.record_status,
        },
        "entries": entries,
        "teeth": [
            {
                "tooth_fdi": tooth.tooth_fdi,
                "status": tooth.status,
                "note": tooth.note,
                "updated_at": tooth.updated_at,
            }
            for tooth in teeth
        ],
        "prescriptions": prescriptions,
        "plan_items": plan_items,
    }


async def create_clinical_entry(
    db: AsyncSession,
    *,
    patient: Patient,
    actor: User,
    kind: str,
    title: str,
    body: str | None = None,
    tooth_fdi: int | None = None,
    appointment_id: int | None = None,
    doctor_id: int | None = None,
    commit: bool = True,
) -> ClinicalEntry:
    """Append one clinical entry and audit it in the same transaction."""
    _validate_kind(kind)
    clean_tooth = _validate_tooth_fdi(tooth_fdi)

    resolved_doctor_id: int | None = None
    if actor.role == "doctor":
        from app.auth.permissions import linked_doctor_id

        resolved_doctor_id = await linked_doctor_id(db, actor)
        if resolved_doctor_id is None:
            raise AppError("DOCTOR_ACCOUNT_NOT_LINKED")
    elif doctor_id is not None:
        doctor = await db.get(Doctor, doctor_id)
        if doctor is None:
            raise AppError("DOCTOR_NOT_FOUND")
        resolved_doctor_id = int(doctor.id)

    if appointment_id is not None:
        appointment = await db.get(Appointment, appointment_id)
        if appointment is None or appointment.patient_id != patient.id:
            raise AppError("APPOINTMENT_NOT_FOUND")

    clean_title = title.strip()
    if len(clean_title) < 2:
        raise AppError("CLINICAL_ENTRY_INVALID")

    entry = ClinicalEntry(
        patient_id=patient.id,
        doctor_id=resolved_doctor_id,
        appointment_id=appointment_id,
        kind=kind,
        tooth_fdi=clean_tooth,
        title=clean_title,
        body=body.strip() if body else None,
        created_by_user_id=int(actor.id),
        created_at=_utc_now_naive(),
    )
    db.add(entry)

    await audit_service.record_audit(
        db,
        actor=actor,
        action="clinical.entry_create",
        target_label=patient.full_name,
        detail={
            "patient_id": patient.id,
            "kind": kind,
            "tooth_fdi": clean_tooth,
            "appointment_id": appointment_id,
        },
    )

    # One inbox nudge for the owning patient account (best effort).
    if patient.user_id is not None:
        try:
            from app.models.notification import Notification

            db.add(
                Notification(
                    user_id=int(patient.user_id),
                    kind="clinical_entry",
                    title="پرونده شما به‌روزرسانی شد",
                    body=f"یک یادداشت درمانی جدید ({'هشدار حساسیت' if kind == 'allergy' else 'یادداشت'}) در پرونده شما ثبت شد.",
                    appointment_id=None,
                    is_read=False,
                    created_at=_utc_now_naive(),
                )
            )
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to compose clinical-entry notification")

    if commit:
        await db.commit()
        await db.refresh(entry)
    else:
        await db.flush()
    return entry


async def set_tooth_status(
    db: AsyncSession,
    *,
    patient: Patient,
    actor: User,
    tooth_fdi: int,
    status: str,
    note: str | None = None,
    commit: bool = True,
) -> ToothStatus:
    """Upsert one tooth's chart status and audit the change."""
    _validate_tooth_fdi(tooth_fdi)
    _validate_status(status)

    existing = (
        await db.execute(
            select(ToothStatus).where(
                ToothStatus.patient_id == patient.id,
                ToothStatus.tooth_fdi == tooth_fdi,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        tooth = ToothStatus(
            patient_id=patient.id,
            tooth_fdi=tooth_fdi,
            status=status,
            note=note.strip() if note else None,
            updated_by_user_id=int(actor.id),
            updated_at=_utc_now_naive(),
        )
        db.add(tooth)
    else:
        tooth = existing
        tooth.status = status
        tooth.note = note.strip() if note else None
        tooth.updated_by_user_id = int(actor.id)
        tooth.updated_at = _utc_now_naive()

    await audit_service.record_audit(
        db,
        actor=actor,
        action="clinical.tooth_status",
        target_label=patient.full_name,
        detail={
            "patient_id": patient.id,
            "tooth_fdi": tooth_fdi,
            "status": status,
        },
    )

    if commit:
        await db.commit()
        await db.refresh(tooth)
    else:
        await db.flush()
    return tooth


async def _resolve_doctor_id(
    db: AsyncSession,
    actor: User,
    doctor_id: int | None,
) -> int | None:
    """Resolve the treating doctor from the account or an explicit choice."""
    if actor.role == "doctor":
        from app.auth.permissions import linked_doctor_id

        resolved = await linked_doctor_id(db, actor)
        if resolved is None:
            raise AppError("DOCTOR_ACCOUNT_NOT_LINKED")
        return resolved
    if doctor_id is None:
        return None
    doctor = await db.get(Doctor, doctor_id)
    if doctor is None:
        raise AppError("DOCTOR_NOT_FOUND")
    return int(doctor.id)


async def _validate_patient_appointment(
    db: AsyncSession,
    patient: Patient,
    appointment_id: int | None,
) -> None:
    if appointment_id is None:
        return
    appointment = await db.get(Appointment, appointment_id)
    if appointment is None or appointment.patient_id != patient.id:
        raise AppError("APPOINTMENT_NOT_FOUND")


def _clean_items(items: list[dict[str, object]]) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    for item in items:
        name = str(item.get("name") or "").strip()
        if len(name) < 2:
            raise AppError("PRESCRIPTION_INVALID")
        line = {"name": name}
        for field in ("dose", "frequency", "duration"):
            value = str(item.get(field) or "").strip()
            if value:
                line[field] = value
        cleaned.append(line)
    if not cleaned:
        raise AppError("PRESCRIPTION_INVALID")
    return cleaned


async def create_prescription(
    db: AsyncSession,
    *,
    patient: Patient,
    actor: User,
    items: list[dict[str, object]],
    notes: str | None = None,
    appointment_id: int | None = None,
    doctor_id: int | None = None,
    commit: bool = True,
) -> Prescription:
    """Append one structured prescription and audit it."""
    resolved_doctor_id = await _resolve_doctor_id(db, actor, doctor_id)
    await _validate_patient_appointment(db, patient, appointment_id)
    clean_items = _clean_items(items)

    prescription = Prescription(
        patient_id=patient.id,
        doctor_id=resolved_doctor_id,
        appointment_id=appointment_id,
        items=clean_items,
        notes=notes.strip() if notes else None,
        created_by_user_id=int(actor.id),
        created_at=_utc_now_naive(),
    )
    db.add(prescription)

    await audit_service.record_audit(
        db,
        actor=actor,
        action="clinical.prescription_create",
        target_label=patient.full_name,
        detail={
            "patient_id": patient.id,
            "item_count": len(clean_items),
            "appointment_id": appointment_id,
        },
    )

    if patient.user_id is not None:
        from app.models.notification import Notification

        db.add(
            Notification(
                user_id=int(patient.user_id),
                kind="clinical_entry",
                title="نسخه جدید در پرونده شما",
                body="پزشک برای شما نسخه‌ای ثبت کرد؛ جزئیات را در پرونده سلامت ببینید.",
                appointment_id=None,
                is_read=False,
                created_at=_utc_now_naive(),
            )
        )

    if commit:
        await db.commit()
        await db.refresh(prescription)
    else:
        await db.flush()
    return prescription


async def create_plan_item(
    db: AsyncSession,
    *,
    patient: Patient,
    actor: User,
    title: str,
    tooth_fdi: int | None = None,
    notes: str | None = None,
    doctor_id: int | None = None,
    commit: bool = True,
) -> TreatmentPlanItem:
    """Append one planned procedure to the treatment roadmap."""
    clean_title = (title or "").strip()
    if len(clean_title) < 2:
        raise AppError("TREATMENT_PLAN_INVALID")
    clean_tooth = _validate_tooth_fdi(tooth_fdi)
    resolved_doctor_id = await _resolve_doctor_id(db, actor, doctor_id)
    now = _utc_now_naive()

    item = TreatmentPlanItem(
        patient_id=patient.id,
        doctor_id=resolved_doctor_id,
        tooth_fdi=clean_tooth,
        title=clean_title,
        status="planned",
        notes=notes.strip() if notes else None,
        created_by_user_id=int(actor.id),
        created_at=now,
        updated_at=now,
    )
    db.add(item)

    await audit_service.record_audit(
        db,
        actor=actor,
        action="clinical.plan_item_create",
        target_label=patient.full_name,
        detail={
            "patient_id": patient.id,
            "tooth_fdi": clean_tooth,
            "status": "planned",
        },
    )

    if commit:
        await db.commit()
        await db.refresh(item)
    else:
        await db.flush()
    return item


async def create_plan_item_draft(
    db: AsyncSession,
    *,
    patient: Patient,
    actor: User,
    title: str,
    tooth_fdi: int | None = None,
    notes: str | None = None,
    commit: bool = True,
) -> TreatmentPlanItem:
    """Append one draft plan item proposed through the chat agent.

    Mirrors :func:`create_plan_item` (same validation, doctor resolution and
    audit discipline) but the row is born ``draft``: it is a proposal for the
    treating doctor to review, never a live roadmap entry, and this function
    never moves it to any other status.
    """
    clean_title = (title or "").strip()
    if len(clean_title) < 2:
        raise AppError("TREATMENT_PLAN_INVALID")
    clean_tooth = _validate_tooth_fdi(tooth_fdi)
    resolved_doctor_id = await _resolve_doctor_id(db, actor, None)
    now = _utc_now_naive()

    item = TreatmentPlanItem(
        patient_id=patient.id,
        doctor_id=resolved_doctor_id,
        tooth_fdi=clean_tooth,
        title=clean_title,
        status="draft",
        notes=notes.strip() if notes else None,
        created_by_user_id=int(actor.id),
        created_at=now,
        updated_at=now,
    )
    db.add(item)

    await audit_service.record_audit(
        db,
        actor=actor,
        action="clinical.plan_item_draft_create",
        target_label=patient.full_name,
        detail={
            "patient_id": patient.id,
            "tooth_fdi": clean_tooth,
            "status": "draft",
            "via": "agent",
        },
    )

    if commit:
        await db.commit()
        await db.refresh(item)
    else:
        await db.flush()
    return item


async def update_plan_item_status(
    db: AsyncSession,
    *,
    patient: Patient,
    actor: User,
    item_id: int,
    status: str,
    notes: str | None = None,
    commit: bool = True,
) -> TreatmentPlanItem:
    """Move one plan item through its lifecycle (audited)."""
    if status not in TREATMENT_PLAN_STATUSES:
        raise AppError("TREATMENT_PLAN_INVALID")
    item = await db.get(TreatmentPlanItem, item_id)
    if item is None or item.patient_id != patient.id:
        raise AppError("TREATMENT_PLAN_ITEM_NOT_FOUND")

    item.status = status
    if notes is not None:
        item.notes = notes.strip() or None
    item.updated_at = _utc_now_naive()

    await audit_service.record_audit(
        db,
        actor=actor,
        action="clinical.plan_item_update",
        target_label=patient.full_name,
        detail={
            "patient_id": patient.id,
            "item_id": item.id,
            "status": status,
        },
    )

    if commit:
        await db.commit()
        await db.refresh(item)
    else:
        await db.flush()
    return item
