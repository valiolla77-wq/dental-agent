from pydantic import BaseModel


class DentalServiceCreate(BaseModel):
    name: str
    description: str | None = None


class DentalServiceUpdate(BaseModel):
    name: str
    description: str | None = None
    is_active: bool


class DentalServiceResponse(BaseModel):
    id: int
    name: str
    description: str | None
    is_active: bool

    model_config = {"from_attributes": True}
