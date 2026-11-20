"""Clinical record endpoints: patient self-view and staff write surface.

- ``GET /clinical/me``            → the authenticated patient account's full
  health record bundle (every owned patient record, entries + tooth chart).
- ``GET /clinical/patients/{id}`` → staff view of one record (matrix-checked).
- ``POST /clinical/patients/{id}/entries`` → append an entry (admin/doctor).
- ``PUT  /clinical/patients/{id}/teeth/{fdi}`` → set one tooth's chart status
  (admin/doctor).

Patient ownership never comes from the URL for self-access: ``/clinical/me``
resolves the owned record set from the authenticated session only.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.permissions import (
    actor_role,
    ensure_patient_scope,
    linked_patient_ids,
)
from app.database import get_db
from app.errors import AppError
from app.models.patient import Patient
from app.models.user import User
from app.schemas.clinical import (
    ClinicalEntryCreate,
    ClinicalEntryResponse,
    MyHealthRecordResponse,
    PatientClinicalRecord,
    PrescriptionCreate,
    PrescriptionResponse,
    ToothStatusResponse,
    ToothStatusSet,
    TreatmentPlanItemCreate,
    TreatmentPlanItemResponse,
    TreatmentPlanItemUpdate,
)
from app.services import clinical_service

router = APIRouter(prefix="/clinical", tags=["ClinicalRecord"])


async def _load_patient(db: AsyncSession, patient_id: int) -> Patient:
    patient = await db.get(Patient, patient_id)
    if patient is None:
        raise AppError("PATIENT_NOT_FOUND")
    return patient


@router.get("/me", response_model=MyHealthRecordResponse)
async def my_health_record(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full health record for every patient owned by this account."""
    if actor_role(current_user) != "patient":
        raise AppError("COMMON_FORBIDDEN")
    linked = await linked_patient_ids(db, current_user)
    if not linked:
        raise AppError("PATIENT_ACCOUNT_NOT_LINKED")

    records: list[PatientClinicalRecord] = []
    for patient_id in linked:
        patient = await _load_patient(db, patient_id)
        view = await clinical_service.get_patient_clinical_view(db, patient)
        records.append(PatientClinicalRecord.model_validate(view))
    return MyHealthRecordResponse(records=records)


@router.get("/patients/{patient_id}", response_model=PatientClinicalRecord)
async def patient_clinical_record(
    patient_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Staff read access to one patient's clinical record."""
    await ensure_patient_scope(db, current_user, patient_id, "clinical:read")
    patient = await _load_patient(db, patient_id)
    view = await clinical_service.get_patient_clinical_view(db, patient)
    return PatientClinicalRecord.model_validate(view)


@router.post(
    "/patients/{patient_id}/entries",
    response_model=ClinicalEntryResponse,
    status_code=201,
)
async def create_clinical_entry(
    patient_id: int,
    payload: ClinicalEntryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Append a treatment note, allergy alert or clinical note."""
    await ensure_patient_scope(db, current_user, patient_id, "clinical:write")
    patient = await _load_patient(db, patient_id)
    entry = await clinical_service.create_clinical_entry(
        db,
        patient=patient,
        actor=current_user,
        kind=payload.kind,
        title=payload.title,
        body=payload.body,
        tooth_fdi=payload.tooth_fdi,
        appointment_id=payload.appointment_id,
    )
    view = await clinical_service.get_patient_clinical_view(db, patient)
    created = next(item for item in view["entries"] if item["id"] == entry.id)
    return ClinicalEntryResponse.model_validate(created)


@router.post(
    "/patients/{patient_id}/prescriptions",
    response_model=PrescriptionResponse,
    status_code=201,
)
async def create_prescription(
    patient_id: int,
    payload: PrescriptionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Write a structured prescription (admin/doctor only)."""
    await ensure_patient_scope(db, current_user, patient_id, "clinical:write")
    patient = await _load_patient(db, patient_id)
    prescription = await clinical_service.create_prescription(
        db,
        patient=patient,
        actor=current_user,
        items=[item.model_dump() for item in payload.items],
        notes=payload.notes,
        appointment_id=payload.appointment_id,
        doctor_id=payload.doctor_id,
    )
    view = await clinical_service.get_patient_clinical_view(db, patient)
    created = next(
        item for item in view["prescriptions"] if item["id"] == prescription.id
    )
    return PrescriptionResponse.model_validate(created)


@router.post(
    "/patients/{patient_id}/plan-items",
    response_model=TreatmentPlanItemResponse,
    status_code=201,
)
async def create_plan_item(
    patient_id: int,
    payload: TreatmentPlanItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a planned procedure to the treatment roadmap."""
    await ensure_patient_scope(db, current_user, patient_id, "clinical:write")
    patient = await _load_patient(db, patient_id)
    item = await clinical_service.create_plan_item(
        db,
        patient=patient,
        actor=current_user,
        title=payload.title,
        tooth_fdi=payload.tooth_fdi,
        notes=payload.notes,
        doctor_id=payload.doctor_id,
    )
    view = await clinical_service.get_patient_clinical_view(db, patient)
    created = next(
        row for row in view["plan_items"] if row["id"] == item.id
    )
    return TreatmentPlanItemResponse.model_validate(created)


@router.put(
    "/patients/{patient_id}/plan-items/{item_id}",
    response_model=TreatmentPlanItemResponse,
)
async def update_plan_item(
    patient_id: int,
    item_id: int,
    payload: TreatmentPlanItemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Move one plan item through planned → in progress → completed."""
    await ensure_patient_scope(db, current_user, patient_id, "clinical:write")
    patient = await _load_patient(db, patient_id)
    item = await clinical_service.update_plan_item_status(
        db,
        patient=patient,
        actor=current_user,
        item_id=item_id,
        status=payload.status,
        notes=payload.notes,
    )
    view = await clinical_service.get_patient_clinical_view(db, patient)
    updated = next(
        row for row in view["plan_items"] if row["id"] == item.id
    )
    return TreatmentPlanItemResponse.model_validate(updated)


@router.put(
    "/patients/{patient_id}/teeth/{tooth_fdi}",
    response_model=ToothStatusResponse,
)
async def set_tooth_status(
    patient_id: int,
    tooth_fdi: int,
    payload: ToothStatusSet,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set (or reset) one tooth's condition on the dental chart."""
    await ensure_patient_scope(db, current_user, patient_id, "clinical:write")
    patient = await _load_patient(db, patient_id)
    tooth = await clinical_service.set_tooth_status(
        db,
        patient=patient,
        actor=current_user,
        tooth_fdi=tooth_fdi,
        status=payload.status,
        note=payload.note,
    )
    return ToothStatusResponse.model_validate(tooth)
