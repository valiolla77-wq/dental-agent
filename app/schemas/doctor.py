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


class DoctorPublicResponse(BaseModel):
    """Public catalog view of a doctor: no phone number.

    Used by every endpoint reachable by non-admin users (patients,
    receptionists, doctors browsing the clinic catalog). The phone stays
    private to admin management endpoints that use DoctorResponse.
    """

    id: int
    full_name: str
    specialty: str
    is_active: bool

    model_config = {
        "from_attributes": True
    }
