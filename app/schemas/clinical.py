"""Request/response schemas for the clinical record (entries + tooth chart)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.clinical_entry import CLINICAL_ENTRY_KINDS
from app.models.tooth_status import TOOTH_STATUSES

ClinicalKind = Literal["treatment", "allergy", "note"]


class ClinicalEntryCreate(BaseModel):
    kind: ClinicalKind
    title: str = Field(min_length=2, max_length=200)
    body: str | None = Field(default=None, max_length=4000)
    tooth_fdi: int | None = Field(default=None, ge=11, le=48)
    appointment_id: int | None = None


class ToothStatusSet(BaseModel):
    status: Literal["healthy", "treated", "needs_treatment", "extracted"]
    note: str | None = Field(default=None, max_length=300)


class ClinicalEntryResponse(BaseModel):
    id: int
    patient_id: int
    doctor_id: int | None
    doctor_name: str | None = None
    appointment_id: int | None
    kind: str
    tooth_fdi: int | None
    title: str
    body: str | None
    created_by_name: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ToothStatusResponse(BaseModel):
    tooth_fdi: int
    status: str
    note: str | None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class MedicationLine(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    dose: str | None = Field(default=None, max_length=80)
    frequency: str | None = Field(default=None, max_length=80)
    duration: str | None = Field(default=None, max_length=80)


class PrescriptionCreate(BaseModel):
    items: list[MedicationLine] = Field(min_length=1, max_length=20)
    notes: str | None = Field(default=None, max_length=2000)
    appointment_id: int | None = None
    doctor_id: int | None = None


class PrescriptionResponse(BaseModel):
    id: int
    patient_id: int
    doctor_id: int | None
    doctor_name: str | None = None
    appointment_id: int | None
    items: list[dict]
    notes: str | None
    created_by_name: str | None = None
    created_at: datetime
    cancelled_at: datetime | None = None

    model_config = {"from_attributes": True}


class TreatmentPlanItemCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    tooth_fdi: int | None = Field(default=None, ge=11, le=48)
    notes: str | None = Field(default=None, max_length=2000)
    doctor_id: int | None = None


class TreatmentPlanItemUpdate(BaseModel):
    status: Literal["planned", "in_progress", "completed", "cancelled"]
    notes: str | None = Field(default=None, max_length=2000)


class TreatmentPlanItemResponse(BaseModel):
    id: int
    patient_id: int
    doctor_id: int | None
    doctor_name: str | None = None
    tooth_fdi: int | None
    title: str
    status: str
    notes: str | None
    created_by_name: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PatientClinicalRecord(BaseModel):
    """Everything the health-record UI needs for one patient record."""

    patient: dict
    entries: list[ClinicalEntryResponse]
    teeth: list[ToothStatusResponse]
    prescriptions: list[PrescriptionResponse] = Field(default_factory=list)
    plan_items: list[TreatmentPlanItemResponse] = Field(default_factory=list)


class MyHealthRecordResponse(BaseModel):
    """Patient-account scoped bundle: one record per owned patient."""

    records: list[PatientClinicalRecord]


# Re-exported so routers (and tests) can validate against the same catalogs.
CLINICAL_KINDS = CLINICAL_ENTRY_KINDS
TOOTH_STATUS_VALUES = TOOTH_STATUSES
