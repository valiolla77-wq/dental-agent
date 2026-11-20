"""Admin-only operational health summary.

The public liveness and readiness probes stay in ``app.main`` and expose no
details. This schema is deliberately limited to provider *names* and booleans:
no API keys, base URLs, database paths, phone numbers, or patient data.
"""

from typing import Literal

from pydantic import BaseModel


class SystemHealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    uptime_seconds: int
    database: Literal["ok", "unavailable"]
    sms_provider: str
    assistant_provider: str
    assistant_configured: bool
