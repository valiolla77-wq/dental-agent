"""Read-only access to the append-only staff audit trail. Admin only."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.database import get_db
from app.models.audit_log import AuditLog
from app.models.user import User

router = APIRouter(
    prefix="/audit-logs",
    tags=["Audit Logs"],
)


class AuditLogResponse(BaseModel):
    id: int
    actor_user_id: int | None = None
    actor_phone: str | None = None
    action: str
    target_user_id: int | None = None
    target_label: str | None = None
    detail: dict | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


@router.get("/", response_model=list[AuditLogResponse])
async def list_audit_logs(
    limit: int = Query(default=100, ge=1, le=300),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(default=None, max_length=60),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Newest-first audit trail with a hard page size.

    Rows are append-only: there is no update or delete endpoint, so the
    trail cannot be edited or erased through the API.
    """
    query = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    if action:
        query = query.where(AuditLog.action == action)
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    return [
        AuditLogResponse.model_validate(row) for row in result.scalars().all()
    ]
