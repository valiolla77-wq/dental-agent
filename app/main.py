import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.auth import auth_router
from app.auth import bale as bale_otp
from app.database import database_is_ready, init_db
from app.devtools.sms_panel import router as dev_sms_panel_router
from app.error_handling import configure_error_handling
from app.routers.agent_chat import router as agent_chat_router
from app.routers.appointments import router as appointments_router
from app.routers.audit_logs import router as audit_logs_router
from app.routers.clinical import router as clinical_router
from app.routers.dental_services import router as dental_services_router
from app.routers.doctor_schedules import router as doctor_schedules_router
from app.routers.doctors import router as doctors_router
from app.routers.feedback import router as feedback_router
from app.routers.notifications import router as notifications_router
from app.routers.patients import router as patients_router
from app.routers.reports import router as reports_router
from app.routers.system_health import router as system_health_router
from app.routers.users import router as users_router
from app.routers.visit_ratings import router as visit_ratings_router
from app.startup_checks import validate_runtime_config

_WEB_DIR = Path(__file__).resolve().parent.parent / "web"
_WEB_INDEX_PAGE = _WEB_DIR / "index.html"
_WEB_ASSETS = _WEB_DIR / "assets"

# Modern React web client (source: ``webapp/``, build with ``npm run build``).
# When the bundle exists it is served at ``/app`` + ``/app-assets``; otherwise
# the legacy static page under ``web/`` remains the fallback so the app is
# always runnable without a Node toolchain.
_WEBAPP_DIR = Path(__file__).resolve().parent.parent / "webapp"
_WEBAPP_INDEX_PAGE = _WEBAPP_DIR / "dist" / "index.html"
_WEBAPP_ASSETS_DIR = _WEBAPP_DIR / "dist"

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_runtime_config()
    await init_db()
    # Best-effort background poller for the Bale OTP channel; a no-op unless
    # OTP_PROVIDER=bale with a token. Never blocks or fails startup.
    bale_otp.start_bale_poller()
    yield
    bale_otp.stop_bale_poller()


app = FastAPI(
    title="Dental Agent",
    description="Dental clinic management system with an Agentic AI assistant",
    version="0.2.0",
    lifespan=lifespan,
)

configure_error_handling(app)

app.include_router(auth_router)
app.include_router(agent_chat_router)
app.include_router(feedback_router)
app.include_router(dev_sms_panel_router)
app.include_router(users_router)
app.include_router(audit_logs_router)
app.include_router(patients_router)
app.include_router(doctors_router)
app.include_router(doctor_schedules_router)
app.include_router(appointments_router)
app.include_router(dental_services_router)
app.include_router(reports_router)
app.include_router(clinical_router)
app.include_router(notifications_router)
app.include_router(visit_ratings_router)
app.include_router(system_health_router)

@app.get("/")
def root():
    return {
        "message": "Dental Agent API is running",
        "status": "ok",
        "web_app": "/app",
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/health/ready")
async def health_ready():
    """Readiness probe: the process can reach its database.

    Liveness (``/health``) stays dependency-free so an orchestrator can tell a
    dead process from a temporarily unavailable database. Neither endpoint
    exposes connection details, credentials, or row data.
    """
    if await database_is_ready():
        return {"status": "ready", "checks": {"database": "ok"}}
    logger.warning("Readiness check failed: database unavailable")
    return JSONResponse(
        status_code=503,
        content={"status": "not_ready", "checks": {"database": "unavailable"}},
    )


@app.get("/app", include_in_schema=False)
@app.get("/app/", include_in_schema=False)
def web_app_page():
    """Serve the clinic web application (React bundle when built, legacy page otherwise)."""
    if _WEBAPP_INDEX_PAGE.is_file():
        return FileResponse(_WEBAPP_INDEX_PAGE, media_type="text/html")
    return FileResponse(_WEB_INDEX_PAGE, media_type="text/html")


@app.get("/staff", include_in_schema=False)
@app.get("/staff/", include_in_schema=False)
def staff_portal_page():
    """Staff back-office portal: the same SPA, staff login door selected.

    The React bundle picks the portal from the pathname; both doors share one
    build so a redeploy never desynchronises patient and staff clients.
    """
    if _WEBAPP_INDEX_PAGE.is_file():
        return FileResponse(_WEBAPP_INDEX_PAGE, media_type="text/html")
    return FileResponse(_WEB_INDEX_PAGE, media_type="text/html")


app.mount(
    "/app-assets",
    StaticFiles(
        directory=_WEBAPP_ASSETS_DIR
        if _WEBAPP_INDEX_PAGE.is_file()
        else _WEB_ASSETS
    ),
    name="app-assets",
)
