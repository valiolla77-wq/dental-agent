"""Schemas for the in-app notification inbox."""

from datetime import datetime

from pydantic import BaseModel


class NotificationItem(BaseModel):
    id: int
    kind: str
    title: str
    body: str | None
    appointment_id: int | None
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationsResponse(BaseModel):
    items: list[NotificationItem]
    unread_count: int


class MarkReadResponse(BaseModel):
    id: int
    is_read: bool


class ReadAllResponse(BaseModel):
    updated: int
