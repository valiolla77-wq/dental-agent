"""Post-visit satisfaction ratings.

A patient account may rate an appointment exactly once, only when the slot
is in the past and the appointment was not cancelled. The clinic summary is
administrator-only and closes the quality loop on the dashboard.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import ensure_appointment_access
from app.errors import AppError
from app.models.user import User
from app.models.visit_rating import VISIT_RATING_MAX, VISIT_RATING_MIN, VisitRating


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def create_visit_rating(
    db: AsyncSession,
    *,
    actor: User,
    appointment_id: int,
    rating: int,
    comment: str | None = None,
) -> VisitRating:
    """Validate, persist and return one rating for a past appointment."""
    if not (VISIT_RATING_MIN <= rating <= VISIT_RATING_MAX):
        raise AppError("VISIT_RATING_INVALID")

    appointment = await ensure_appointment_access(
        db, actor, appointment_id, "appointment:read"
    )

    from app.services.appointment_service import clinic_now

    if appointment.status == "cancelled":
        raise AppError("VISIT_NOT_RATEABLE")
    if appointment.appointment_time >= clinic_now():
        raise AppError("VISIT_NOT_RATEABLE")

    existing = (
        await db.execute(
            select(VisitRating.id).where(
                VisitRating.appointment_id == appointment.id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise AppError("VISIT_RATING_ALREADY_SUBMITTED")

    record = VisitRating(
        user_id=int(actor.id),
        appointment_id=appointment.id,
        patient_id=appointment.patient_id,
        rating=rating,
        comment=comment.strip() if comment else None,
        created_at=_utc_now_naive(),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def list_my_ratings(db: AsyncSession, actor: User) -> list[VisitRating]:
    result = await db.execute(
        select(VisitRating)
        .where(VisitRating.user_id == actor.id)
        .order_by(VisitRating.created_at.desc())
        .limit(200)
    )
    return list(result.scalars().all())


async def rating_summary(db: AsyncSession) -> dict[str, object]:
    """Clinic-wide averages (all-time and last 30 days). Admin-only caller."""
    total = await db.scalar(select(func.count(VisitRating.id)))
    average = await db.scalar(select(func.avg(VisitRating.rating)))

    cutoff = _utc_now_naive() - timedelta(days=30)
    average_30d = await db.scalar(
        select(func.avg(VisitRating.rating)).where(
            VisitRating.created_at >= cutoff
        )
    )

    return {
        "count": int(total or 0),
        "average": round(float(average), 2) if average is not None else 0.0,
        "average_30d": round(float(average_30d), 2) if average_30d is not None else 0.0,
    }
