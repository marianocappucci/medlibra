"""MedLibra app factory: wires LibraGenda plus MedLibra's own patient and
clinical-note extensions, and mounts the routers."""

from fastapi import FastAPI

from libragenda.database import configure, get_engine, get_session_factory
from libragenda.catalog_repository import SqlAlchemyCatalogRepository
from libragenda.sqlalchemy_repository import Base, SqlAlchemyAppointmentRepository

from .routers import appointments, clinical_notes, demo, health
from .routers import patients as patients_router
from .services.appointments import AppointmentService
from .services.clinical_notes import ClinicalNoteRepository
from .services.patients import PatientRepository


def create_app(database_url: str) -> FastAPI:
    """Build the vertical app after configuring LibraGenda's PostgreSQL port."""
    configure(database_url)
    Base.metadata.create_all(get_engine())  # demo only; deploy uses Alembic
    sessions = get_session_factory()
    catalog = SqlAlchemyCatalogRepository(sessions)
    appointment_repository = SqlAlchemyAppointmentRepository(sessions)

    app = FastAPI(title="MedLibra")
    app.state.catalog = catalog
    app.state.appointment_service = AppointmentService(catalog, appointment_repository)
    app.state.patients = PatientRepository(catalog, sessions)
    app.state.clinical_notes = ClinicalNoteRepository(sessions)

    app.include_router(health.router)
    app.include_router(demo.router)
    app.include_router(appointments.router)
    app.include_router(patients_router.router)
    app.include_router(clinical_notes.router)

    return app
