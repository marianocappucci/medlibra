"""El formato de los instantes que salen por la API: siempre UTC.

🔴 **Por qué existe este módulo.** Las columnas `DateTime(timezone=True)` viajan
a PostgreSQL como `timestamptz`, y un `timestamptz` se renderiza en la zona de
la **sesión del servidor** — no en una zona propia. Mientras el contenedor de la
base corrió en UTC eso daba `2026-07-20T13:00:00Z` y nadie lo pensó dos veces.
Al ponerle la zona de Argentina (2026-08-23, para que el reloj del proceso y el
de la base coincidan) el mismo instante pasó a salir como
`2026-07-20T10:00:00-03:00`.

Es el **mismo momento** y es ISO 8601 válido: ningún parser se rompe. Pero es un
cambio de contrato para cualquier consumidor que compare strings, y sobre todo
es un formato de salida decidido por una variable de entorno de un contenedor.
Eso es exactamente la clase de dependencia implícita que la normalización de
huso horario vino a sacar.

**La regla, entonces:** el cable va en UTC y la hora local es una decisión de
**presentación**, que se toma en el frontend con el `timeZone` de la sucursal —
que puede no ser UTC-3. Es la misma separación que ya rige para el formato
`dd-mm-aaaa`: la base y las APIs en ISO, el formateo al mostrar.

**Cómo se usa.** En vez de declarar `created_at: datetime` en el modelo de
respuesta, se declara `created_at: InstanteUTC`. Un solo lugar por producto
decide el formato, en vez de un `field_serializer` repetido por router.
"""
from __future__ import annotations

from datetime import UTC, datetime, timezone
from typing import Annotated

from pydantic import PlainSerializer


def a_utc(valor: datetime) -> datetime:
    if valor.tzinfo is None:
        # Convención de almacenamiento del dominio: lo naive ya es UTC. Pasa con
        # SQLite, que se come el offset en el viaje de ida y vuelta y devuelve
        # el `DateTime(timezone=True)` sin `tzinfo`.
        return valor.replace(tzinfo=UTC)
    return valor.astimezone(UTC)


#: `datetime` que se serializa siempre en UTC, sin importar la zona de la sesión
#: de PostgreSQL ni la del proceso.
InstanteUTC = Annotated[datetime, PlainSerializer(a_utc, return_type=datetime)]
