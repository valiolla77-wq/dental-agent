from pydantic import BaseModel


class DoctorCreate(BaseModel):
    full_name: str
    specialty: str
    phone: str


class DoctorUpdate(BaseModel):
    full_name: str
    specialty: str
    phone: str
    is_active: bool


class DoctorResponse(BaseModel):
    id: int
    full_name: str
    specialty: str
    phone: str
    is_active: bool

    model_config = {
        "from_attributes": True
    }