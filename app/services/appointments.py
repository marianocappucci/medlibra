"""Application service for the appointment booking use case.

Wraps LibraGenda's InMemoryScheduler with the one piece of app-specific
validation the engine can't do on its own (does this service exist at
all) — everything else is delegated straight to LibraGenda's own use
cases and domain exceptions, per CONVENTIONS.md ("no duplicar reglas de
LibraGenda").
"""

from datetime import date, datetime, timezone
from uuid import uuid4

from libragenda import Appointment, InMemoryScheduler
from libragenda.availability_repository import SqlAlchemyAvailabilityRepository
from libragenda.catalog_repository import SqlAlchemyCatalogRepository
from libragenda.repositories import AppointmentRepository

from .branch_hours import BranchHoursRepository


class ServiceNotFound(Exception):
    """Raised when booking references a service that was never registered."""


class OutsideBusinessHours(Exception):
    """Raised when the slot falls outside the resource's branch hours,
    only for branches that actually have hours configured (see
    branch_hours.py's opt-in gating)."""


def _as_utc(starts_at: datetime) -> datetime:
    if starts_at.tzinfo is None:
        return starts_at.replace(tzinfo=timezone.utc)
    return starts_at.astimezone(timezone.utc)


class AppointmentService:
    def __init__(
        self,
        catalog: SqlAlchemyCatalogRepository,
        appointments: AppointmentRepository,
        availability: SqlAlchemyAvailabilityRepository,
        branch_hours: BranchHoursRepository,
    ) -> None:
        self.catalog = catalog
        self.appointments = appointments
        self.availability = availability
        self.branch_hours = branch_hours

    def _check_branch_hours(self, resource_id: str, starts_at: datetime, ends_at: datetime) -> None:
        resource = self.catalog.get_resource(resource_id)
        if resource is None or resource.branch_id is None:
            return
        if not self.branch_hours.is_within_hours(resource.branch_id, starts_at, ends_at):
            raise OutsideBusinessHours(resource.branch_id)

    def create(
        self, resource_id: str, service_id: str, client_id: str, starts_at: datetime
    ) -> Appointment:
        services = {item.id: item for item in self.catalog.list_services()}
        service = services.get(service_id)
        if service is None:
            raise ServiceNotFound(service_id)
        starts_at = _as_utc(starts_at)
        self._check_branch_hours(resource_id, starts_at, starts_at + service.duration)
        windows = [item for _, item in self.availability.list_availability(resource_id)]
        blocks = [item for _, item in self.availability.list_blocks(resource_id)]
        exceptions = [item for _, item in self.availability.list_exceptions(resource_id)]
        scheduler = InMemoryScheduler(
            windows, blocks, exceptions, repository=self.appointments,
        )
        appointment = Appointment(
            str(uuid4()), resource_id, service_id, client_id, starts_at, service.duration,
        )
        scheduler.create(appointment)
        return appointment

    def confirm(self, appointment_id: str) -> Appointment:
        scheduler = InMemoryScheduler(repository=self.appointments)
        return scheduler.confirm(appointment_id)

    def cancel(self, appointment_id: str, reason: str | None = None) -> Appointment:
        scheduler = InMemoryScheduler(repository=self.appointments)
        return scheduler.cancel(appointment_id, reason=reason)

    def complete(self, appointment_id: str) -> Appointment:
        scheduler = InMemoryScheduler(repository=self.appointments)
        return scheduler.complete(appointment_id)

    def reschedule(
        self, appointment_id: str, starts_at: datetime, reason: str | None = None
    ) -> Appointment:
        current = self.appointments.get(appointment_id)
        resource_id = current.resource_id if current is not None else ""
        starts_at = _as_utc(starts_at)
        if current is not None:
            self._check_branch_hours(resource_id, starts_at, starts_at + current.duration)
        windows = [item for _, item in self.availability.list_availability(resource_id)]
        blocks = [item for _, item in self.availability.list_blocks(resource_id)]
        exceptions = [item for _, item in self.availability.list_exceptions(resource_id)]
        scheduler = InMemoryScheduler(
            windows, blocks, exceptions, repository=self.appointments,
        )
        return scheduler.reschedule(appointment_id, starts_at, reason=reason)

    def agenda(self, resource_id: str, day_from: date, day_to: date) -> list[Appointment]:
        return sorted(
            (
                item for item in self.appointments.list()
                if item.resource_id == resource_id
                and day_from <= item.starts_at.date() <= day_to
            ),
            key=lambda item: item.starts_at,
        )
