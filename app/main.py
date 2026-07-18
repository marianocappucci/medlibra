"""Minimal MedLibra integration example.

This is vertical application code, not part of LibraGenda's public HTTP API.
No clinical domain yet (patients/historia clinica come in Fase 1) — this
only proves MedLibra can compose LibraGenda without contaminating the engine.
"""

from datetime import datetime, time
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from libragenda import Appointment, Availability, InMemoryScheduler
from libragenda.database import configure, get_engine, get_session_factory
from libragenda.catalog_repository import SqlAlchemyCatalogRepository
from libragenda.sqlalchemy_repository import Base, SqlAlchemyAppointmentRepository
from libragenda.application import AppointmentConflict, AppointmentUnavailable, InvalidTransition


class SeedRequest(BaseModel):
    resource_id: str
    resource_name: str
    service_id: str
    service_name: str
    client_id: str
    client_name: str
    duration_minutes: int = 30


class AppointmentRequest(BaseModel):
    resource_id: str
    service_id: str
    client_id: str
    starts_at: datetime


def create_app(database_url: str) -> FastAPI:
    """Build the vertical app after configuring LibraGenda's PostgreSQL port."""
    configure(database_url)
    Base.metadata.create_all(get_engine())  # demo only; deploy uses Alembic
    sessions = get_session_factory()
    catalog = SqlAlchemyCatalogRepository(sessions)
    appointments = SqlAlchemyAppointmentRepository(sessions)
    app = FastAPI(title="MedLibra example")

    @app.get("/health")
    def health():
        return {"ok": True, "product": "medlibra-example"}

    @app.post("/demo/seed")
    def seed(data: SeedRequest):
        from datetime import timedelta
        from libragenda import Branch, Client, Resource, Service
        catalog.add_branch(Branch("demo-branch", "Consultorio demo"))
        catalog.add_client(Client(data.client_id, data.client_name))
        catalog.add_resource(Resource(data.resource_id, data.resource_name, "demo-branch"))
        catalog.add_service(Service(data.service_id, data.service_name, timedelta(minutes=data.duration_minutes)))
        return {"ok": True}

    @app.post("/appointments", status_code=201)
    def create_appointment(data: AppointmentRequest):
        services = {item.id: item for item in catalog.list_services()}
        service = services.get(data.service_id)
        if service is None:
            raise HTTPException(404, "service not found")
        scheduler = InMemoryScheduler(
            [Availability(data.resource_id, data.starts_at.weekday(), time(9), time(18))],
            repository=appointments,
        )
        appointment = Appointment(str(uuid4()), data.resource_id, data.service_id, data.client_id, data.starts_at, service.duration)
        try:
            scheduler.create(appointment)
        except AppointmentConflict:
            raise HTTPException(409, "appointment conflict")
        except AppointmentUnavailable:
            raise HTTPException(409, "appointment unavailable")
        return {"id": appointment.id, "status": appointment.status.value, "ends_at": appointment.ends_at}

    @app.post("/appointments/{appointment_id}/confirm")
    def confirm_appointment(appointment_id: str):
        scheduler = InMemoryScheduler(repository=appointments)
        try:
            appointment = scheduler.confirm(appointment_id)
        except InvalidTransition as exc:
            raise HTTPException(409, str(exc))
        except Exception as exc:
            from libragenda import AppointmentNotFound
            if isinstance(exc, AppointmentNotFound):
                raise HTTPException(404, "appointment not found")
            raise
        return {"id": appointment.id, "status": appointment.status.value}

    return app
