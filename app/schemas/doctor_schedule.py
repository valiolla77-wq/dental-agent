from datetime import time

from pydantic import BaseModel


class DoctorScheduleCreate(BaseModel):
    doctor_id: int
    day_of_week: int
    start_time: time
    end_time: time
    slot_duration_minutes: int = 30


class DoctorScheduleResponse(BaseModel):
    id: int
    doctor_id: int
    day_of_week: int
    start_time: time
    end_time: time
    slot_duration_minutes: int
    is_active: bool

    model_config = {
        "from_attributes": True
    }

class DoctorScheduleUpdate(BaseModel):
    day_of_week: int
    start_time: time
    end_time: time
    slot_duration_minutes: int
    is_active: bool