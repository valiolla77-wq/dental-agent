"""In-app notification inbox for every authenticated account.

The listing endpoint for patient accounts also synthesises (idempotently)
24-hour appointment reminders, so the clinic needs no background scheduler
to keep reminders flowing.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.permissions import actor_role, linked_patient_ids
from app.database import get_db
from app.errors import AppError
from app.models.notification import Notification
from app.models.user import User
from app.schemas.notification import (
    MarkReadResponse,
    NotificationItem,
    NotificationsResponse,
    ReadAllResponse,
)
from app.services.notification_service import ensure_upcoming_reminders

router = APIRouter(prefix="/notifications", tags=["Notifications"])

NOTIFICATION_LIST_LIMIT = 50


@router.get("/me", response_model=NotificationsResponse)
async def my_notifications(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Latest notifications for this account plus the unread counter."""
    if actor_role(current_user) == "patient":
        linked = await linked_patient_ids(db, current_user)
        # Reminder synthesis is idempotent and commits only when it adds rows.
        await ensure_upcoming_reminders(
            db, user_id=int(current_user.id), linked_patient_ids=linked
        )

    items = (
        await db.execute(
            select(Notification)
            .where(Notification.user_id == current_user.id)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(NOTIFICATION_LIST_LIMIT)
        )
    ).scalars().all()

    unread = await db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False),
        )
    )

    return NotificationsResponse(
        items=[NotificationItem.model_validate(item) for item in items],
        unread_count=int(unread or 0),
    )


@router.post("/{notification_id}/read", response_model=MarkReadResponse)
async def mark_notification_read(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark one notification read; foreign notifications are 404, not 403.

    Returning the same status for missing and foreign rows avoids leaking
    which notification ids exist outside the caller's inbox.
    """
    notification = await db.get(Notification, notification_id)
    if (
        notification is None
        or notification.user_id != int(current_user.id)
    ):
        raise AppError("NOTIFICATION_NOT_FOUND")
    notification.is_read = True
    await db.commit()
    return MarkReadResponse(id=notification.id, is_read=True)


@router.post("/read-all", response_model=ReadAllResponse)
async def mark_all_notifications_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        update(Notification)
        .where(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False),
        )
        .values(is_read=True)
    )
    await db.commit()
    return ReadAllResponse(updated=int(result.rowcount or 0))
