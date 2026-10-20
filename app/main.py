from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from app.routers.patients import router as patients_router
from app.database import init_db
from app.routers.users import router as users_router
from app.routers.doctors import router as doctors_router
from app.routers.doctor_schedules import router as doctor_schedules_router
from app.routers.appointments import router as appointments_router
from app.routers.dental_services import router as dental_services_router
from app.auth import auth_router
from app.error_handling import configure_error_handling
from app.routers.agent_chat import router as agent_chat_router

_DEMO_CHAT_PAGE = Path(__file__).resolve().parent.parent / "demo" / "chat.html"

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="Dental Agent",
    description="Dental clinic management system with an Agentic AI assistant",
    version="0.1.0",
    lifespan=lifespan,
)

configure_error_handling(app)

app.include_router(auth_router)
app.include_router(agent_chat_router)
app.include_router(users_router)
app.include_router(patients_router)
app.include_router(doctors_router)
app.include_router(doctor_schedules_router)
app.include_router(appointments_router)
app.include_router(dental_services_router)

@app.get("/")
def root():
    return {
        "message": "Dental Agent API is running",
        "status": "ok",
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/demo", include_in_schema=False)
@app.get("/demo/", include_in_schema=False)
def demo_chat_page():
    """Serve the same-origin browser demo for the patient agent chat."""
    return FileResponse(_DEMO_CHAT_PAGE, media_type="text/html")
