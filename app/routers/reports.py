"""Read-only clinic reports for role-scoped dashboards.

Every value is a real SQL aggregate; nothing here is sampled, estimated or
built from model output. The dashboard endpoint is deliberately admin-only:
receptionists and doctors already have their scoped views, and the agent
tools expose the appointment workload to authorized staff sessions only.
"""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.permissions import require_action
from app.database import get_db
from app.models.user import User
from app.services import report_service

router = APIRouter(
    prefix="/reports",
    tags=["Reports"],
)


@router.get("/dashboard")
async def dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Whole-clinic overview plus the default appointment workload window.

    Returns ``{"overview": ..., "appointments": ...}`` with counts computed
    at request time in the clinic timezone. Admin role only (fail-closed).
    """
    require_action(current_user, "report:overview")
    overview = await report_service.clinic_overview_stats(db)
    appointments = await report_service.clinic_appointments_report(db)
    return {
        "overview": overview,
        "appointments": appointments,
    }
