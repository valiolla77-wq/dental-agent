"""Operational health for clinic administrators.

This endpoint is intentionally separate from the public probes:

- ``/health`` is a dependency-free liveness check.
- ``/health/ready`` verifies the database without leaking details.
- ``/system/health`` is authenticated, admin-only, and returns a compact
  summary for the in-app «سلامت سامانه» page.

Nothing here returns credentials, provider URLs, database paths, or patient
data. Provider *names* and a configured/not-configured boolean are enough for
an administrator to triage an outage.
"""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.agent.llm import load_llm_config
from app.auth.dependencies import require_admin
from app.auth.sms import provider_name as sms_provider_name
from app.database import database_is_ready
from app.models.user import User
from app.schemas.system_health import SystemHealthResponse

router = APIRouter(prefix="/system", tags=["system"])

_STARTED_AT = time.monotonic()


@router.get("/health", response_model=SystemHealthResponse)
async def system_health(
    request: Request,
    _admin: Annotated[User, Depends(require_admin)],
) -> SystemHealthResponse:
    """Summary for the admin health page; never raises for a DB outage."""
    database_ok = await database_is_ready()

    try:
        llm_config = load_llm_config()
        assistant_provider = llm_config.provider
        assistant_configured = True
    except ValueError:
        # Missing or invalid AGENT_LLM_* values: the assistant is unavailable,
        # but the rest of the clinic system is still usable.
        assistant_provider = "unconfigured"
        assistant_configured = False

    return SystemHealthResponse(
        status="ok" if database_ok else "degraded",
        version=request.app.version,
        uptime_seconds=max(0, int(time.monotonic() - _STARTED_AT)),
        database="ok" if database_ok else "unavailable",
        sms_provider=sms_provider_name(),
        assistant_provider=assistant_provider,
        assistant_configured=assistant_configured,
    )
