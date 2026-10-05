from pydantic import BaseModel


class PatientCreate(BaseModel):
    national_id: str
    full_name: str
    phone: str


class PatientUpdate(BaseModel):
    full_name: str
    phone: str


class PatientResponse(BaseModel):
    id: int
    national_id: str
    full_name: str
    phone: str

    model_config = {
        "from_attributes": True
    }