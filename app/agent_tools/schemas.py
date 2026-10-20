"""Typed inputs and outputs for agent tool operations."""

from typing import Generic, TypeVar

from pydantic import BaseModel, Field, field_validator, model_validator


class SearchDentalServicesInput(BaseModel):
    query: str | None = Field(default=None, max_length=150)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class FindDoctorsForServiceInput(BaseModel):
    service_id: int = Field(gt=0)


class FindAvailableSlotsInput(BaseModel):
    service_id: int = Field(gt=0)
    doctor_id: int = Field(gt=0)
    appointment_date: str = Field(min_length=1, max_length=20)

    @field_validator("appointment_date")
    @classmethod
    def normalize_date(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("appointment_date cannot be blank")
        return normalized


class FindNearestAppointmentsInput(BaseModel):
    """Optional filters for an automatic 30-day forward search."""

    service_id: int | None = Field(default=None, gt=0)
    doctor_id: int | None = Field(default=None, gt=0)
    days: int = Field(default=30, ge=1, le=60)
    limit: int = Field(default=3, ge=1, le=10)


class GetPatientAppointmentsInput(BaseModel):
    patient_id: int = Field(gt=0)


class CancelAppointmentInput(BaseModel):
    appointment_id: int = Field(gt=0)


class RescheduleAppointmentInput(BaseModel):
    appointment_id: int = Field(gt=0)
    appointment_date: str = Field(min_length=1, max_length=20)
    appointment_time: str = Field(min_length=1, max_length=10)

    @field_validator("appointment_date", "appointment_time")
    @classmethod
    def normalize_schedule_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized


class BookAppointmentInput(BaseModel):
    """Booking input: existing patient_id or all new/existing patient details."""

    doctor_id: int = Field(gt=0)
    service_id: int = Field(gt=0)
    appointment_date: str = Field(min_length=1, max_length=20)
    appointment_time: str = Field(min_length=1, max_length=10)
    patient_id: int | None = Field(default=None, gt=0)
    national_id: str | None = Field(default=None, min_length=1, max_length=10)
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    phone: str | None = Field(default=None, min_length=1, max_length=20)
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("appointment_date", "appointment_time", "national_id", "full_name", "phone")
    @classmethod
    def reject_blank_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def validate_patient_input(self):
        has_patient_id = self.patient_id is not None
        patient_fields = (self.national_id, self.full_name, self.phone)
        has_any_patient_field = any(value is not None for value in patient_fields)
        has_all_patient_fields = all(value is not None for value in patient_fields)

        if has_patient_id == has_any_patient_field:
            raise ValueError(
                "Provide either patient_id or national_id, full_name, and phone"
            )
        if has_any_patient_field and not has_all_patient_fields:
            raise ValueError(
                "national_id, full_name, and phone must all be provided"
            )
        return self


class DentalServiceToolItem(BaseModel):
    id: int
    name: str
    description: str | None


class DoctorToolItem(BaseModel):
    id: int
    full_name: str
    specialty: str


class AvailableSlotsToolData(BaseModel):
    service_id: int
    doctor_id: int
    appointment_date: str
    available_slots: list[str]


class NearestAppointmentToolItem(BaseModel):
    doctor_id: int
    doctor_name: str
    service_id: int
    service_name: str
    appointment_date: str
    appointment_time: str


class NearestAppointmentsToolData(BaseModel):
    search_days: int
    appointments: list[NearestAppointmentToolItem]


class PatientAppointmentToolItem(BaseModel):
    appointment_id: int
    doctor_id: int
    service_id: int
    appointment_date: str
    appointment_time: str
    status: str


class BookAppointmentToolData(BaseModel):
    appointment_id: int
    patient_id: int
    doctor_id: int
    service_id: int
    appointment_time: str
    status: str


class CancelAppointmentToolData(BaseModel):
    appointment_id: int
    status: str


class RescheduleAppointmentToolData(BaseModel):
    appointment_id: int
    patient_id: int
    doctor_id: int
    service_id: int
    appointment_time: str
    status: str


class AgentToolError(BaseModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


ResultData = TypeVar("ResultData")


class AgentToolResult(BaseModel, Generic[ResultData]):
    """Structured success or catalogued failure returned to an agent runtime."""

    ok: bool
    data: ResultData | None = None
    error: AgentToolError | None = None
