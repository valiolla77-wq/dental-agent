from pydantic import BaseModel


class UserCreate(BaseModel):
    full_name: str
    phone: str
    password: str
    role: str


class UserResponse(BaseModel):
    id: int
    full_name: str
    phone: str
    role: str
    is_active: bool

    model_config = {
        "from_attributes": True
    }