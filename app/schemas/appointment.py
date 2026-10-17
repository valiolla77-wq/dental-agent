from pydantic import BaseModel, field_validator, model_validator


class AppointmentCreate(BaseModel):
    """Create a booking with patient_id or all three new-patient fields."""

    patient_id: int | None = None
    national_id: str | None = None
    full_name: str | None = None
    phone: str | None = None
    doctor_id: int
    service_id: int
    appointment_date: str
    appointment_time: str
    reason: str | None = None

    @model_validator(mode="after")
    def validate_patient_input(self):
        has_patient_id = self.patient_id is not None
        patient_fields = (self.national_id, self.full_name, self.phone)
        has_any_patient_field = any(value is not None for value in patient_fields)
        has_all_patient_fields = all(
            value is not None and value.strip() for value in patient_fields
        )

        if has_patient_id == has_any_patient_field:
            raise ValueError(
                "Provide either patient_id or national_id, full_name, and phone"
            )
        if has_any_patient_field and not has_all_patient_fields:
            raise ValueError(
                "national_id, full_name, and phone must all be provided"
            )
        return self


class AppointmentReschedule(BaseModel):
    """New date/time for rescheduling a scheduled appointment."""

    appointment_date: str
    appointment_time: str

    @field_validator("appointment_date", "appointment_time")
    @classmethod
    def normalize_schedule_text(cls, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized


class AppointmentResponse(BaseModel):
    id: int
    patient_id: int
    doctor_id: int
    service_id: int
    appointment_date: str
    appointment_time: str
    status: str
    reason: str | None

    model_config = {
        "from_attributes": True
    }
