from pydantic import BaseModel, Field


class DoctorCreate(BaseModel):
    full_name: str
    specialty: str
    phone: str
    service_ids: list[int] = Field(default_factory=list)


class DoctorUpdate(BaseModel):
    full_name: str
    specialty: str
    phone: str
    is_active: bool
    service_ids: list[int] = Field(default_factory=list)


class DoctorResponse(BaseModel):
    id: int
    full_name: str
    specialty: str
    phone: str
    is_active: bool

    model_config = {
        "from_attributes": True
    }
