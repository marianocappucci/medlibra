"""Application service for the appointment booking use case.

Hardcoded 9-18 weekly window for now (same as the old app/main.py demo it
was ported from) -- real configurable availability per resource is a later
Fase 1 item (see TASKS.md "Próximas"), not this round's scope.
"""
from datetime import datetime, time, timezone
from uuid import uuid4

from libragenda import Appointment, Availability, InMemoryScheduler
from libragenda.catalog_repository import SqlAlchemyCatalogRepository
from libragenda.repositories import AppointmentRepository


class ServiceNotFound(Exception):
    """Raised when booking references a service that was never registered."""


def _as_utc(starts_at: datetime) -> datetime:
    if starts_at.tzinfo is None:
        return starts_at.replace(tzinfo=timezone.utc)
    return starts_at.astimezone(timezone.utc)


class AppointmentService:
    def __init__(
        self, catalog: SqlAlchemyCatalogRepository, appointments: AppointmentRepository,
    ) -> None:
        self.catalog = catalog
        self.appointments = appointments

    def create(
        self, resource_id: str, service_id: str, client_id: str, starts_at: datetime
    ) -> Appointment:
        services = {item.id: item for item in self.catalog.list_services()}
        service = services.get(service_id)
        if service is None:
            raise ServiceNotFound(service_id)
        starts_at = _as_utc(starts_at)
        scheduler = InMemoryScheduler(
            [Availability(resource_id, starts_at.weekday(), time(9), time(18))],
            repository=self.appointments,
        )
        appointment = Appointment(
            str(uuid4()), resource_id, service_id, client_id, starts_at, service.duration,
        )
        scheduler.create(appointment)
        return appointment

    def confirm(self, appointment_id: str) -> Appointment:
        scheduler = InMemoryScheduler(repository=self.appointments)
        return scheduler.confirm(appointment_id)
