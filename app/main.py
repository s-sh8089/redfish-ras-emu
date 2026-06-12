import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.auth import unauthorized_response, validate_token
from app.database import init_db
from app.routes import (
    chassis,
    event_service,
    log_service,
    managers,
    metadata,
    power_equipment,
    service_root,
    session_service,
    task_service,
    telemetry_service,
    ups,
)
from app.sse_manager import sse_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    sse_manager.set_loop(asyncio.get_event_loop())
    yield


app = FastAPI(
    title="Redfish RAS Emulator",
    description="Redfish API simulator for RAS rack power and sensor management (DSP2056)",
    version="1.0.0",
    lifespan=lifespan,
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_AUTH_EXEMPT = frozenset([
    "/redfish/v1/",
    "/redfish/v1",
    "/redfish/v1/$metadata",
    "/redfish/v1/odata",
    "/redfish/v1/SessionService",
    "/redfish/v1/SessionService/",
    "/redfish/v1/EventService/SSE",  # auth handled in handler (supports ?token= for browser EventSource)
    "/docs",
    "/openapi.json",
    "/redoc",
])


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path in _AUTH_EXEMPT:
        return await call_next(request)
    if path == "/redfish/v1/SessionService/Sessions" and request.method == "POST":
        return await call_next(request)
    token = request.headers.get("X-Auth-Token")
    if not token or not validate_token(token):
        return unauthorized_response()
    return await call_next(request)


app.include_router(metadata.router)
app.include_router(service_root.router)
app.include_router(power_equipment.router)
app.include_router(ups.router)
app.include_router(chassis.router)
app.include_router(managers.router)
app.include_router(event_service.router)
app.include_router(log_service.router)
app.include_router(session_service.router)
app.include_router(task_service.router)
app.include_router(telemetry_service.router)
