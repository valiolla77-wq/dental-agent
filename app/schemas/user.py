from pydantic import BaseModel, Field
from typing import Literal


class UserCreate(BaseModel):
    full_name: str
    phone: str
    password: str
    role: Literal["admin", "receptionist", "doctor", "patient"] = Field(
        description="Staff role assigned explicitly by an administrator."
    )


class UserResponse(BaseModel):
    id: int
    full_name: str
    phone: str
    role: str
    is_active: bool

    model_config = {
        "from_attributes": True
    }