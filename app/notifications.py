"""Cuándo se le recuerda un turno al paciente.

Qué se le dice y por dónde sale vive en `app/avisos.py` (ADR-049); el envío, el registro y que no salga dos veces, en el motor
(`libracore.avisos`, ADR-090). Hasta el ADR-049 acá había un `LoggingNotificationPort` que sólo escribía al log; se fue.
"""
from datetime import timedelta

from libragenda import ReminderPolicy

# Fijo por ahora -- no configurable por sucursal/servicio, nadie lo pidio
# todavia. Cambiar aca si los tiempos de aviso necesitan ajustarse.
#
# El `id` de cada politica forma parte de la CLAVE del aviso (`agenda:{turno}:{politica}`): cambiarlo hace que un turno
# que ya recibio su "24h" reciba otro. Agregar una politica nueva es seguro; renombrar una, no.
DEFAULT_REMINDER_POLICIES = [
    ReminderPolicy("24h", timedelta(hours=24)),
    ReminderPolicy("2h", timedelta(hours=2)),
]
