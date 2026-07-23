"""Dashboard: turnos, pacientes y recordatorios/señas -- resumen de
lectura pura sobre repositorios ya existentes (LibraGenda + PatientRepository
propio), sin tabla ni estado propio. Alcance del primer corte elegido por el
usuario (`AskUserQuestion`): turnos, pacientes, recordatorios y señas --
facturación/caja queda para una entrega futura.
"""
from datetime import date, datetime, time, timezone

from libragenda import AppointmentStatus, DepositStatus
from libragenda.repositories import AppointmentRepository, DepositRepository, SentReminderRepository

from .patients import PatientRepository


def _day_range_utc(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(date_from, time.min, tzinfo=timezone.utc),
        datetime.combine(date_to, time.max, tzinfo=timezone.utc),
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
        today = datetime.now(timezone.utc).date()
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
