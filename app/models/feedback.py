"""User-submitted error reports and suggestions.

Reports are deliberately append-only. They keep the submitted message plus a
short, server-captured log tail so support can reproduce a failure without
asking the user for backend access. Secrets are never logged by application
code, and the log buffer omits request bodies and SQL parameters.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FeedbackReport(Base):
    __tablename__ = "feedback_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Free-form client context (page, message, request id, session id). Never
    # trusted for authorization or shown to other users.
    context: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Compact tail of backend application logs at submission time.
    logs: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="new",
        server_default="new",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_feedback_reports_category_created", "category", "created_at"),
    )
