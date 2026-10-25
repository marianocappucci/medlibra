"""La demanda espontánea que se anota en un nodo de LibraEdge sin conexión, y su vuelta en el central (ADR-045).

Decisión del humano (2026-10-25): *demanda espontánea, sí*. Anotar a quien llega sin turno, llamarlo y cerrar su atención
pasa en el mostrador y no se pisa con los turnos de la web. Es una fila del día, no un turno (ADR-031), y el motor no la
conoce: vive en el producto, así que la costura con el outbox es `libragenda.atencion_en_nodo.encolar_en_nodo` y el
aplicador es de este módulo.

## Por qué el número de llegada del nodo es provisorio

`walkins` tiene `UNIQUE (block_id, day, arrival_order)`: el orden de llegada de la fila. Si el nodo anotara a alguien con
el siguiente número de **su** copia de la fila y en la web se anotara a otro con el mismo, el espejo (que escribe con el
número del central) chocaría con la clave única y **frenaría la bajada**. Por eso el nodo anota con un número
**negativo** (`-1`, `-2`...; los del central son siempre positivos) y lo ordena **después** de los que ya estaban; el
central, al aplicar la llegada, le da el siguiente número real de esa fila (`max + 1`) y la fila baja por el espejo con su
número definitivo. El orden de llegada que queda es el de **cuando subió**, que sólo difiere del de la sala si en la web
se anotó a alguien mientras la PC estaba sin conexión (y entonces el orden entre los dos no estaba definido).

## Las operaciones

| `operation_type` | Qué sube |
|---|---|
| `walkin.registrado` | una llegada nueva (`walkin_id`, `block_id`, `day`, `client_id`, `service_id`, `created_at`) |
| `walkin.estado` | el pase de una llegada a `in_progress`, `completed` o `cancelled` (`walkin_id`, `estado`, `at`) |

`aggregate_type = "walkin"`, `schema_version = 1`, `version 1`. El `client_id` puede ser un paciente provisorio
(`"-N"`): el central lo traduce con el mapeo de `agenda_clients`; si el alta del paciente quedó en revisión manual, la
llegada se rechaza (`SinMapeo`) en vez de quedar atada a nadie, y se reintenta al resolverla.

`walkin.estado` aplica las mismas transiciones que la web (`TRANSICIONES`): la misma otra vez no hace nada
(idempotente) y un pase que ya no es válido —la llegada se canceló en la web— va a revisión manual, sin perderse.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from .. import offline

VERSION = 1

TIPO_WALKIN_REGISTRADO = "walkin.registrado"
TIPO_WALKIN_ESTADO = "walkin.estado"
TIPOS = (TIPO_WALKIN_REGISTRADO, TIPO_WALKIN_ESTADO)
AGREGADO_WALKIN = "walkin"

#: A qué estados se puede llevar una llegada (los que tienen un camino desde `waiting`).
ESTADOS_DE_DESTINO = ("in_progress", "completed", "cancelled")


class WalkinDelNodoError(ValueError):
    """Una operación de demanda espontánea que el central no puede aplicar. Es un `ValueError` a propósito: el receptor de
    LibraEdge la manda a revisión manual y el nodo no traba la cola (ADR-020 de libraedge)."""


# ── En el nodo ───────────────────────────────────────────────────────────────


def en_un_nodo() -> bool:
    return offline.en_un_nodo()


def llegada_provisoria(sesion, block_id: str, dia: date) -> int:
    """El número de llegada **provisorio** (negativo) de la próxima llegada de ese bloque ese día: `-1`, `-2`... El
    mínimo cuenta a los cancelados, igual que el máximo de la web: un número no se reusa."""
    from sqlalchemy import func, select

    from .walkins import WalkinRow

    menor = sesion.scalar(select(func.min(WalkinRow.arrival_order)).where(
        WalkinRow.block_id == block_id, WalkinRow.day == dia, WalkinRow.arrival_order < 0,
    ))
    return (menor or 0) - 1


def encolar_registrada(sesion, fila: Any) -> bool:
    """Encola `walkin.registrado` de la llegada `fila` (un `WalkinRow` ya guardado) **en la transacción de `sesion`**.
    Fuera de un nodo no hace nada y devuelve `False`."""
    from libragenda import atencion_en_nodo

    return atencion_en_nodo.encolar_en_nodo(sesion, TIPO_WALKIN_REGISTRADO, AGREGADO_WALKIN, fila.id, {
        "version": VERSION,
        "walkin_id": fila.id,
        "block_id": fila.block_id,
        "day": fila.day.isoformat(),
        "client_id": fila.client_id,
        "service_id": fila.service_id,
        "created_at": fila.created_at.isoformat(),
    })


def encolar_estado(sesion, walkin_id: str, estado: str) -> bool:
    """Encola `walkin.estado`. Fuera de un nodo no hace nada y devuelve `False`."""
    from libragenda import atencion_en_nodo

    return atencion_en_nodo.encolar_en_nodo(sesion, TIPO_WALKIN_ESTADO, AGREGADO_WALKIN, walkin_id, {
        "version": VERSION, "walkin_id": walkin_id, "estado": estado, "at": datetime.now(UTC).isoformat(),
    })


# ── En el central: validar ───────────────────────────────────────────────────


def _texto(datos: Mapping, campo: str, operacion, maximo: int = 100) -> str:
    valor = datos.get(campo)
    if not isinstance(valor, str) or not valor.strip() or len(valor) > maximo:
        raise WalkinDelNodoError(f"{campo} {valor!r} del nodo {operacion.node_id} no es un texto de 1 a {maximo}")
    return valor


def _instante(datos: Mapping, campo: str, operacion) -> datetime:
    try:
        fecha = datetime.fromisoformat(datos.get(campo))
    except (TypeError, ValueError) as exc:
        raise WalkinDelNodoError(f"{campo} {datos.get(campo)!r} no es una fecha ISO 8601") from exc
    if fecha.tzinfo is None:
        raise WalkinDelNodoError(f"{campo} {datos.get(campo)!r} no trae zona horaria")
    return fecha


def _datos(operacion, tipo: str) -> Mapping:
    if operacion.operation_type != tipo:
        raise WalkinDelNodoError(f"se esperaba {tipo}, llegó {operacion.operation_type!r}")
    if operacion.schema_version != offline.SCHEMA_VERSION:
        raise WalkinDelNodoError(
            f"schema {operacion.schema_version} de {tipo} desconocido (se entiende {offline.SCHEMA_VERSION})"
        )
    datos = operacion.payload
    if datos.get("version") != VERSION:
        raise WalkinDelNodoError(
            f"versión {datos.get('version')!r} de los datos de {tipo} desconocida (se entiende {VERSION})"
        )
    return datos


# ── En el central: aplicar ───────────────────────────────────────────────────


def aplicar_walkin_registrado(conn, operacion) -> None:
    """Aplica `walkin.registrado`: crea la llegada **con el mismo id** y el siguiente número de llegada de su fila, con el
    paciente traducido. Idempotente. Un bloque, una prestación o un paciente que no existen son `ValueError` (revisión
    manual)."""
    from libraedge import mapeo

    from .walkins import ESPERANDO

    datos = _datos(operacion, TIPO_WALKIN_REGISTRADO)
    walkin_id = _texto(datos, "walkin_id", operacion)
    block_id = _texto(datos, "block_id", operacion)
    service_id = _texto(datos, "service_id", operacion)
    try:
        dia = date.fromisoformat(datos.get("day"))
    except (TypeError, ValueError) as exc:
        raise WalkinDelNodoError(f"day {datos.get('day')!r} no es una fecha ISO 8601") from exc
    creada = _instante(datos, "created_at", operacion)
    cliente = mapeo.traducir_id(conn, operacion.node_id, "agenda_clients", _texto(datos, "client_id", operacion))

    for tabla, id_, que in (
        ("agenda_blocks", block_id, "bloque de agenda"), ("services", service_id, "prestación"),
        ("agenda_clients", cliente, "paciente"),
    ):
        if conn.execute(f"SELECT 1 FROM {tabla} WHERE id = ?", (id_,)).fetchone() is None:
            raise WalkinDelNodoError(f"el {que} {id_!r} de la llegada del nodo {operacion.node_id} no existe en el central")

    # Dos llegadas a la vez a la misma fila esperan una a la otra: sin esto las dos leen el mismo máximo.
    conn.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"walkins:{block_id}:{dia.isoformat()}",))
    ultimo = conn.execute(
        "SELECT COALESCE(MAX(arrival_order), 0) FROM walkins WHERE block_id = ? AND day = ?", (block_id, dia),
    ).fetchone()[0]
    # El máximo incluye a los cancelados a propósito (ver `walkins.py`): el número dice el orden en que se llegó.
    conn.execute(
        "INSERT INTO walkins (id, block_id, day, client_id, service_id, arrival_order, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (id) DO NOTHING",
        (walkin_id, block_id, dia, cliente, service_id, max(int(ultimo), 0) + 1, ESPERANDO, creada),
    )


def aplicar_walkin_estado(conn, operacion) -> None:
    """Aplica `walkin.estado` con las transiciones de la web. Idempotente: el mismo estado otra vez no hace nada."""
    from .walkins import TRANSICIONES

    datos = _datos(operacion, TIPO_WALKIN_ESTADO)
    walkin_id = _texto(datos, "walkin_id", operacion)
    estado = datos.get("estado")
    if estado not in ESTADOS_DE_DESTINO:
        raise WalkinDelNodoError(f"estado {estado!r} desconocido (se entiende {list(ESTADOS_DE_DESTINO)})")
    _instante(datos, "at", operacion)

    fila = conn.execute("SELECT status FROM walkins WHERE id = ? FOR UPDATE", (walkin_id,)).fetchone()
    if fila is None:
        raise WalkinDelNodoError(
            f"la llegada {walkin_id!r} del nodo {operacion.node_id} no existe en el central: falta aplicar la que la "
            "creó (quedó en revisión manual, o todavía no subió)"
        )
    actual = fila[0]
    if actual == estado:
        return
    if estado not in TRANSICIONES.get(actual, set()):
        raise WalkinDelNodoError(
            f"la llegada {walkin_id!r} se marcó {estado} en el nodo {operacion.node_id}, pero en el central está "
            f"{actual}, desde donde no se puede: revisar a mano"
        )
    conn.execute("UPDATE walkins SET status = ? WHERE id = ?", (estado, walkin_id))


def registrar_en(despachador):
    """Registra `walkin.registrado` y `walkin.estado` en un `libraedge.sync.despacho.Despachador` y lo devuelve."""
    despachador.registrar(TIPO_WALKIN_REGISTRADO, offline.SCHEMA_VERSION, aplicar_walkin_registrado)
    despachador.registrar(TIPO_WALKIN_ESTADO, offline.SCHEMA_VERSION, aplicar_walkin_estado)
    return despachador
