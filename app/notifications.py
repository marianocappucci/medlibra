"""Placeholder NotificationPort: logs instead of actually sending.

No hay proveedor de email/SMS/WhatsApp elegido todavia. Loguea cada
recordatorio vencido para seguimiento manual hasta que se reemplace por un
canal real -- decision acordada con el usuario, ver DECISIONS.md ADR-XXX.
"""
import logging
from datetime import timedelta

from libragenda import ReminderNotification, ReminderPolicy

logger = logging.getLogger("medlibra.reminders")

# Fijo por ahora -- no configurable por sucursal/servicio, nadie lo pidio
# todavia. Cambiar aca si los tiempos de aviso necesitan ajustarse.
DEFAULT_REMINDER_POLICIES = [
    ReminderPolicy("24h", timedelta(hours=24)),
    ReminderPolicy("2h", timedelta(hours=2)),
]


class LoggingNotificationPort:
    """Implementa libragenda.NotificationPort (estructuralmente -- el
    Protocol no es @runtime_checkable, asi que esto no se verifica con
    isinstance, solo matchea la firma `send(notification)`)."""

    def send(self, notification: ReminderNotification) -> None:
        logger.info(
            "reminder due: appointment=%s policy=%s client=%s starts_at=%s",
            notification.appointment_id, notification.policy_id,
            notification.client_id, notification.starts_at,
        )
