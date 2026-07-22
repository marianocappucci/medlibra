"""MedLibra app factory: wires LibraGenda plus MedLibra's own patient and
clinical-note extensions, and mounts the routers."""

from fastapi import FastAPI

from libragenda.availability_repository import SqlAlchemyAvailabilityRepository
from libragenda.database import configure, get_engine, get_session_factory
from libragenda.catalog_repository import SqlAlchemyCatalogRepository
from libragenda.sqlalchemy_repository import Base, SqlAlchemyAppointmentRepository

from .routers import agenda, appointments, availability, branches, clinical_notes, health, resources, services
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
    availability_repository = SqlAlchemyAvailabilityRepository(sessions)

    app = FastAPI(title="MedLibra")
    app.state.catalog = catalog
    app.state.availability = availability_repository
    app.state.appointment_service = AppointmentService(
        catalog, appointment_repository, availability_repository,
    )
    app.state.patients = PatientRepository(catalog, sessions)
    app.state.clinical_notes = ClinicalNoteRepository(sessions)

    app.include_router(health.router)
    app.include_router(branches.router)
    app.include_router(resources.router)
    app.include_router(services.router)
    app.include_router(availability.router)
    app.include_router(patients_router.router)
    app.include_router(clinical_notes.router)
    app.include_router(appointments.router)
    app.include_router(agenda.router)

    return app
