"""Schemas for post-visit satisfaction ratings."""

from datetime import datetime

from pydantic import BaseModel, Field


class VisitRatingCreate(BaseModel):
    appointment_id: int
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class VisitRatingItem(BaseModel):
    id: int
    appointment_id: int
    patient_id: int
    rating: int
    comment: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class VisitRatingSummary(BaseModel):
    count: int
    average: float
    average_30d: float
