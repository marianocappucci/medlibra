"""Dashboard: turnos, pacientes y recordatorios/señas -- resumen de
lectura pura sobre repositorios ya existentes (LibraGenda + PatientRepository
propio), sin tabla ni estado propio. Alcance del primer corte elegido por el
usuario (`AskUserQuestion`): turnos, pacientes, recordatorios y señas --
facturación/caja queda para una entrega futura.
"""
from datetime import UTC, date, datetime, time, timedelta, timezone

from libragenda import AppointmentStatus, DepositStatus
from libragenda.repositories import AppointmentRepository, DepositRepository, SentReminderRepository

from .patients import PatientRepository

#: Zona del negocio. Argentina es UTC-3 fijo, sin horario de verano.
_ZONA = timezone(timedelta(hours=-3))


def _day_range_utc(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    """Los días **locales** del rango, expresados como instantes UTC.

    🔴 Acá los días se armaban con `tzinfo=timezone.utc`, o sea que el rango
    significaba *"del 00:00 UTC al 23:59 UTC"*. Y en el mismo `summary()` la
    mitad de facturación compara ese rango contra fechas **locales** —las
    facturas se estampan con `date.today()`—, así que **la misma función usaba
    dos relojes**: entre las 21:00 y las 24:00 de Argentina, los turnos y los
    pacientes se contaban de un día y las facturas de otro.

    Idéntico a lo que tenía Gestiolibra, y encontrado por el mismo camino: los
    dos dashboards salieron del mismo molde. Ahora el rango significa una sola
    cosa —días del negocio— y las dos mitades responden por el mismo período.
    """
    return (
        datetime.combine(date_from, time.min, tzinfo=_ZONA).astimezone(UTC),
        datetime.combine(date_to, time.max, tzinfo=_ZONA).astimezone(UTC),
    )


class DashboardService:
    def __init__(
        self,
        appointments: AppointmentRepository,
        patients: PatientRepository,
        reminders: SentReminderRepository,
        deposits: DepositRepository,
    ) -> None:
        self.appointments = appointments
        self.patients = patients
        self.reminders = reminders
        self.deposits = deposits

    def summary(self, date_from: date, date_to: date) -> dict:
        range_start, range_end = _day_range_utc(date_from, date_to)
        all_appointments = list(self.appointments.list())
        in_range = [
            item for item in all_appointments if range_start <= item.starts_at <= range_end
        ]
        por_estado = {status.value: 0 for status in AppointmentStatus}
        for item in in_range:
            por_estado[item.status.value] += 1
        today = datetime.now(UTC).date()
        turnos_hoy = sum(1 for item in all_appointments if item.starts_at.date() == today)

        return {
            "date_from": date_from,
            "date_to": date_to,
            "turnos": {
                "total_en_periodo": len(in_range),
                "por_estado": por_estado,
                "hoy": turnos_hoy,
            },
            "pacientes": {
                "total_activos": self.patients.count_active(),
                "nuevos_en_periodo": self.patients.count_created_between(range_start, range_end),
            },
            "recordatorios_enviados_en_periodo": len(
                self.reminders.list_sent(range_start, range_end)
            ),
            "senas_pendientes": len(self.deposits.list_by_status(DepositStatus.PENDING)),
        }
