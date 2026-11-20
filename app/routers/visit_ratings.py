"""Post-visit satisfaction ratings (patient submissions, admin summary)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.permissions import require_action
from app.database import get_db
from app.models.user import User
from app.schemas.visit_rating import (
    VisitRatingCreate,
    VisitRatingItem,
    VisitRatingSummary,
)
from app.services import visit_rating_service

router = APIRouter(prefix="/visit-ratings", tags=["VisitRatings"])


@router.post("/", response_model=VisitRatingItem, status_code=201)
async def submit_visit_rating(
    payload: VisitRatingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rate a past visit from 1 to 5 stars, once per appointment."""
    require_action(current_user, "visit_rating:create")
    record = await visit_rating_service.create_visit_rating(
        db,
        actor=current_user,
        appointment_id=payload.appointment_id,
        rating=payload.rating,
        comment=payload.comment,
    )
    return VisitRatingItem.model_validate(record)


@router.get("/mine", response_model=list[VisitRatingItem])
async def my_visit_ratings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The caller's own ratings (used to hide already-rated visits)."""
    records = await visit_rating_service.list_my_ratings(db, current_user)
    return [VisitRatingItem.model_validate(record) for record in records]


@router.get("/summary", response_model=VisitRatingSummary)
async def visit_rating_summary(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_user),
):
    """Clinic-wide satisfaction averages. Admin only."""
    require_action(_admin, "report:feedback")
    return VisitRatingSummary.model_validate(
        await visit_rating_service.rating_summary(db)
    )
