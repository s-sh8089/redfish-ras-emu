from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.routes import (
    chassis,
    event_service,
    managers,
    power_equipment,
    service_root,
    ups,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Redfish RAS Emulator",
    description="Redfish API simulator for RAS rack power and sensor management (DSP2056)",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(service_root.router)
app.include_router(power_equipment.router)
app.include_router(ups.router)
app.include_router(chassis.router)
app.include_router(managers.router)
app.include_router(event_service.router)
