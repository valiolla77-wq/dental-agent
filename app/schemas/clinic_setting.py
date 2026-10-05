from pydantic import BaseModel, Field


class ClinicSettingUpdate(BaseModel):
    max_appointments_per_day: int = Field(
        default=0,
        ge=0,
    )

    max_appointments_per_week: int = Field(
        default=0,
        ge=0,
    )

    max_appointments_per_month: int = Field(
        default=0,
        ge=0,
    )


class ClinicSettingResponse(BaseModel):
    id: int
    max_appointments_per_day: int
    max_appointments_per_week: int
    max_appointments_per_month: int

    model_config = {
        "from_attributes": True
    }