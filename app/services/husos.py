"""Dónde la hora de pared se vuelve un instante, y al revés.

🔴 **Por qué existe este módulo** (2026-08-22). El producto maneja las dos
cosas a la vez y no son la misma:

- **Hora de pared**: lo que alguien escribe en un formulario y lo que dice el
  reloj de la sucursal. Es la unidad de la disponibilidad —`Availability` es
  `(día de la semana, 09:00, 19:00)`—, del horario de atención
  (`branch_hours`) y de las excepciones.
- **Instante**: un punto en la línea de tiempo, que es lo que se guarda
  (`DateTime(timezone=True)`, normalizado a UTC por LibraGenda).

`libragenda/timezones.py` fija de qué lado va la conversión: *"verticals are
expected to collect wall-clock times ... and convert at the boundary using
this module, rather than teaching the scheduling engine about civil time
zones"*. O sea que el borde es este producto, y este archivo es ese borde.

Mezclar los dos terrenos fue el defecto que se arregló el 2026-08-22: el turno
se convertía a UTC antes de validarlo contra ventanas cargadas en hora local,
y con UTC-3 una sucursal abierta de 9 a 19 rechazaba todo lo que empezara
después de las 16 (*"El horario elegido está fuera del horario de atención"*).
"""

from datetime import datetime

from libragenda.timezones import to_branch_local, to_utc

#: Con qué huso se trabaja cuando el recurso no cuelga de ninguna sucursal (o
#: la sucursal fue borrada). UTC y no la zona de Argentina: sin sucursal no hay
#: hora local que valga, y con offset cero el instante queda igual a como se
#: ingresó — que es lo que hacía antes de que existiera esta conversión.
SIN_SUCURSAL = "UTC"


def zona_del_recurso(catalog, resource_id: str) -> str:
    """El huso de la sucursal del recurso (`Branch.timezone`)."""
    resource = catalog.get_resource(resource_id)
    branch = (
        catalog.get_branch(resource.branch_id)
        if resource is not None and resource.branch_id else None
    )
    return branch.timezone if branch is not None else SIN_SUCURSAL


def hora_de_pared(instante: datetime, zona: str) -> datetime:
    """El mismo instante, como hora de pared de `zona` y **sin** `tzinfo`.

    Se le saca el huso a propósito. Lo que el motor compara son `.weekday()`,
    `.time()` y `.date()`, y con un valor *aware* esos tres ya darían lo
    correcto — pero `find_conflicts` compara turnos entre sí, y mezclar uno
    aware con otro naive es un `TypeError`. El terreno de validación queda
    naive entero, sin excepción.
    """
    return to_branch_local(instante, zona).replace(tzinfo=None)


def como_instante(valor: datetime, zona: str) -> datetime:
    """El valor que llegó por la API, como instante.

    Un valor **naive** es la hora civil que produce un `datetime-local` del
    formulario: ya es hora de pared de la sucursal, y se interpreta con su
    huso. Uno **aware** (un offset explícito en el pedido) ya es un instante y
    se respeta tal cual.
    """
    return valor if valor.tzinfo is not None else to_utc(valor, zona)


def como_hora_de_pared(valor: datetime, zona: str) -> datetime:
    """Lo simétrico de `como_instante`: el valor de la API en hora de pared.

    Un naive se toma tal cual (ya es hora de pared); un aware se re-expresa en
    la zona de la sucursal.
    """
    return valor if valor.tzinfo is None else hora_de_pared(valor, zona)
