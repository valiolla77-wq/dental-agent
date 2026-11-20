"""Authenticated user feedback: error reports and product suggestions."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    feedback_rate_limit,
    get_current_user,
    require_admin,
)
from app.database import get_db
from app.logging_buffer import recent_logs
from app.models.feedback import FeedbackReport
from app.models.user import User

router = APIRouter(prefix="/feedback", tags=["Feedback"])


class FeedbackCreate(BaseModel):
    category: Literal["error", "suggestion"]
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=120)
    page: str | None = Field(default=None, max_length=200)
    assistant_message: str | None = Field(default=None, max_length=4000)
    user_message: str | None = Field(default=None, max_length=4000)
    request_id: str | None = Field(default=None, max_length=120)


class FeedbackResponse(BaseModel):
    id: int
    status: str
    message: str


class FeedbackListItem(BaseModel):
    id: int
    category: str
    message: str
    context: dict | None = None
    logs: str | None = None
    status: str
    user_id: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.post(
    "/",
    response_model=FeedbackResponse,
    status_code=201,
    dependencies=[Depends(feedback_rate_limit)],
)
async def create_feedback(
    payload: FeedbackCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Store the report plus a short server log tail for error reports."""
    context = {
        "role": current_user.role,
        "session_id": payload.session_id,
        "page": payload.page,
        "assistant_message": payload.assistant_message,
        "user_message": payload.user_message,
        "request_id": payload.request_id,
    }
    report = FeedbackReport(
        user_id=current_user.id,
        category=payload.category,
        message=payload.message.strip(),
        context={key: value for key, value in context.items() if value},
        logs=recent_logs(200) if payload.category == "error" else None,
        status="new",
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return FeedbackResponse(
        id=report.id,
        status="received",
        message=(
            "گزارش خطا ثبت شد؛ تیم پشتیبانی بررسی می‌کند."
            if payload.category == "error"
            else "پیشنهاد شما ثبت شد؛ ممنون از بازخوردتان."
        ),
    )


@router.get("/", response_model=list[FeedbackListItem])
async def list_feedback(
    limit: int = Query(default=100, ge=1, le=300),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Admin-only review list, newest first."""
    result = await db.execute(
        select(FeedbackReport)
        .order_by(FeedbackReport.created_at.desc(), FeedbackReport.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
