"""Los pacientes que se dan de alta en un nodo de LibraEdge sin conexión, y su vuelta en el central (ADR-045).

Un consultorio sin internet también recibe a alguien que **no está en la lista**: hay que darlo de alta ahí mismo para
atenderlo y anotarle la consulta (decisión del humano, 2026-10-25: *«número provisorio con cartel»*). Hasta este cambio
el número `p-NNN` salía del contador de la base, y el contador del nodo no tiene nada que ver con el del central: el
mismo `p-043` hubiera sido dos personas.

## Id provisorio de texto

El paciente se guarda con un id **`"-N"`** (`"-1"`, `"-2"`...) de `libraedge.mapeo.siguiente_id_provisorio(texto=True)`
(ADR-026 de LibraEdge). Un id del central nunca empieza con `-`, así que no se cruza con uno que baje por el espejo.
Son **dos filas** con el mismo id: `agenda_clients` (la persona de LibraGenda) y `patients` (la extensión clínica, cuya
clave primaria es a la vez clave foránea a la primera). Las dos tablas tienen su alta en el nodo
(`offline.ALTAS_EN_EL_NODO`) y su propio mapeo.

## La operación

- `operation_type`: `paciente.alta`. `aggregate_type = "paciente"`, `aggregate_id = "<nodo>:paciente:<id>"`.
- La encola `crear_en_el_nodo`, **en la misma transacción** que las dos filas: no queda un paciente sin su operación ni
  una operación de un paciente que no existe.
- `schema_version = 1`. Payload `version 1`: `paciente_id` (`"-N"`), `name`, `phone`, `email`, `active`, `dni`,
  `birth_date`, `cuit`, `condicion_iva`, `creada_at` (ISO con zona).

## Qué hace el central (`aplicar_paciente_alta`, idempotente por `libraedge_mapeo_texto`)

En la transacción del receptor, con SQL propio sobre su conexión (no con las sesiones del dominio: un paciente creado en
una transacción aparte y el mapeo en otra quedarían a medias si se corta entre las dos):

1. Si el mapeo `(nodo, 'patients', id provisorio)` ya está, no crea nada **siempre que el paciente mapeado sea la misma
   persona** (si no, el nodo reusó un id provisorio, una PC reemplazada con el mismo `node_id`: `PacienteDelNodoError`,
   revisión manual; las notas a ese id irían a otra persona). El outbox entrega al menos una vez.
2. Si no, **busca al paciente por DNI** (comparado sin puntos, guiones ni espacios, sin mayúsculas). Si existe, usa **ése**
   y no toca sus datos: el central es la autoridad de la ficha (*«si ya existía con ese DNI, se une a su ficha»*). Se
   prefiere un paciente activo; uno dado de baja también se une (la historia clínica no se parte). **No se deduplica por
   nombre ni por teléfono**: dos «Juan Pérez» sin DNI son dos pacientes (un duplicado se junta a mano; una nota atada a
   otra persona no se nota).
3. Si no existe, lo crea con el próximo `p-NNN` del mismo contador que usa la web (`patient_sequences`), que avanza una
   sola vez por alta.
4. Anota los dos mapeos. Ese mapeo es también lo que le dice al nodo el id definitivo: `libraedge_mapeo_texto` baja por
   el espejo y el nodo reapunta lo que colgaba del provisorio (LibraEdge ADR-021, punto 4).

## Lo verificado sobre `patients.id` (clave primaria y foránea a la vez)

El ADR-026 de LibraEdge dejó «a verificar» el caso en que el nodo ya bajó la ficha definitiva (el central unió al paciente a
uno que ya existía): la clave primaria debería chocar. **Medido con la ficha real de MedLibra y el `MirrorApplier` de
LibraEdge** (PostgreSQL 16, `tests/test_nodo_pacientes.py`):

1. `reapuntar` no *mueve* la fila `patients` del provisorio, la **borra** (la tabla es del espejo: lo que cuelga de una
   provisoria desde una tabla espejada se borra, no se reapunta, y la definitiva ya bajó con su contenido). **La clave
   primaria no choca.**
2. Lo que cuelga de `patients -1` desde otra tabla del espejo (una nota, una receta...) se borra con ella: es la **copia local**
   de lo que el nodo cargó con ese paciente. La operación sigue en el outbox con la nota entera y, cuando el central la aplica,
   **vuelve por el espejo con el mismo uuid**, ya en la ficha definitiva. Entre una cosa y la otra la nota no se ve en la PC
   (en el mismo ciclo, si el central aplicó las operaciones en el mismo `push`; hasta el siguiente si el `push` se cortó).
3. Si `agenda_clients` se reapunta antes que `patients` y hay una nota colgando, el `DELETE` viola la clave foránea de la
   nota; LibraEdge lo deshace (`SAVEPOINT`), lo deja en `sin_reconciliar` y lo reintenta en el barrido del final del ciclo,
   que ya encuentra a `patients` resuelto.

Converge sin duplicar ni perder nada; lo único visible es esa desaparición transitoria de la copia local.

## En el nodo: las guardas

`agenda_clients` y `patients` son tablas del espejo con alta en el nodo: sólo se escriben las filas con id negativo
(ADR-019 de LibraEdge: cualquier otra da SQLSTATE `LE001`). Lo que la base rechazaría con un 500 se contesta antes con un
409 claro: **editar o borrar un paciente** es `sin_conexion` si el nodo no está en línea y `solo_en_el_central` si lo
está; un paciente provisorio tampoco se edita (la operación ya encolada llevaría los datos viejos y el cambio se
perdería cuando baje el definitivo).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from libracore.nodo_offline import SoloEnElCentral

from .. import offline

logger = logging.getLogger(__name__)

#: La forma de los `datos` de la operación. Si cambia, sube: el central rechaza lo que no entiende.
VERSION = 1

TIPO_PACIENTE_ALTA = "paciente.alta"
TIPOS = (TIPO_PACIENTE_ALTA,)
#: El `aggregate_type` de la operación (el `aggregate_id` es `<node_id>:paciente:<id>`).
AGREGADO_PACIENTE = "paciente"

#: Las dos tablas del mapeo de un paciente: la persona de LibraGenda y su extensión clínica.
TABLA_CLIENTES = "agenda_clients"
TABLA_PACIENTES = "patients"

#: Largos de las columnas (el central valida antes de escribir: un `DataError` ajeno no es un `ValueError`).
_LARGOS = {"name": 200, "phone": 50, "email": 254, "dni": 20, "cuit": 20, "condicion_iva": 50}

MENSAJE_SIN_CONEXION = (
    "Este paciente es del central: editarlo o borrarlo espera a que vuelva la conexión con el central."
)
MENSAJE_DEL_CENTRAL = (
    "Los pacientes se editan y se borran desde la web, no desde la PC del consultorio: desde acá sólo se dan de alta."
)
MENSAJE_PROVISORIO = (
    "Este paciente se dio de alta sin conexión y todavía no subió: corregilo desde la web cuando suba."
)
MENSAJE_ID_PROPIO = (
    "Sin conexión el número del paciente lo asigna el sistema cuando vuelve la conexión: no se puede elegir."
)

#: Los números `p-NNN` y cuántos ocupados a mano se saltean antes de rendirse (igual que `PatientRepository`).
SERIE_PACIENTE = "patient"
PREFIJO_ID = "p-"
_ID_GENERADO = re.compile(r"^p-(\d+)$")
INTENTOS_DE_ID = 50


class PacienteDelNodoError(ValueError):
    """Un alta de paciente del nodo que el central no puede aplicar. Es un `ValueError` a propósito: el receptor de
    LibraEdge la manda a revisión manual y el nodo no traba la cola (ADR-020 de libraedge)."""


class AltaDePacienteInvalida(PacienteDelNodoError):
    """El payload de `paciente.alta` no se entiende o trae algo que el central no puede escribir."""


def es_provisorio(paciente_id: str | None) -> bool:
    """Si el paciente se dio de alta en este nodo y todavía no tiene su id definitivo: un id `"-N"`."""
    from libraedge.mapeo import es_provisorio as _es_provisorio

    return paciente_id is not None and _es_provisorio(paciente_id)


# ── En el nodo: el alta ──────────────────────────────────────────────────────


def _iso(valor: datetime | date | None) -> str | None:
    return None if valor is None else valor.isoformat()


def datos_de_alta(paciente_id: str, cliente: Mapping[str, Any], paciente: Mapping[str, Any], *,
                  creada_at: datetime) -> dict:
    """El payload de `paciente.alta`."""
    return {
        "version": VERSION,
        "paciente_id": paciente_id,
        "name": cliente["name"],
        "phone": cliente["phone"],
        "email": cliente["email"],
        "active": bool(cliente["active"]),
        "dni": paciente["dni"],
        "birth_date": _iso(paciente["birth_date"]),
        "cuit": paciente["cuit"],
        "condicion_iva": paciente["condicion_iva"],
        "creada_at": _iso(creada_at),
    }


def crear_en_el_nodo(
    session_factory, *, name: str, phone: str | None, email: str | None, active: bool, dni: str | None,
    birth_date: date | None, cuit: str | None, condicion_iva: str | None,
) -> dict:
    """Da de alta un paciente **en el nodo**: id provisorio `"-N"`, las dos filas y `paciente.alta` en una sola
    transacción. Devuelve el paciente como lo devuelve `PatientRepository` (`id`, `name`, `phone`...).

    Si algo falla, no queda ni el paciente ni la operación (ni el número: la secuencia está en la transacción)."""
    from libraedge.mapeo import siguiente_id_provisorio
    from libragenda.sqlalchemy_repository import ClientRow

    from .patients import PatientRow

    ahora = datetime.now(UTC)
    with session_factory.begin() as sesion:
        paciente_id = siguiente_id_provisorio(offline.conexion_de_la_sesion(sesion), texto=True)
        sesion.add(ClientRow(id=paciente_id, name=name, phone=phone, email=email, active=active))
        sesion.flush()   # `patients.id` tiene clave foránea a `agenda_clients.id`
        sesion.add(PatientRow(
            id=paciente_id, dni=dni, birth_date=birth_date, cuit=cuit, condicion_iva=condicion_iva, created_at=ahora,
        ))
        sesion.flush()
        offline.encolar_operacion(
            sesion, TIPO_PACIENTE_ALTA, AGREGADO_PACIENTE, paciente_id,
            datos_de_alta(
                paciente_id,
                {"name": name, "phone": phone, "email": email, "active": active},
                {"dni": dni, "birth_date": birth_date, "cuit": cuit, "condicion_iva": condicion_iva},
                creada_at=ahora,
            ),
        )
    return {
        "id": paciente_id, "name": name, "phone": phone, "email": email, "active": active, "dni": dni,
        "birth_date": birth_date, "cuit": cuit, "condicion_iva": condicion_iva,
    }


# ── En el nodo: las guardas ──────────────────────────────────────────────────


def exigir_paciente_modificable(paciente_id: str) -> None:
    """En un nodo, editar o borrar un paciente no se puede (el del central es de sólo lectura; el provisorio ya subió con
    sus datos). Fuera de un nodo no hace nada.

    Levanta `SinConexion` (409 `sin_conexion`) si el nodo no está en línea y `SoloEnElCentral` (409
    `solo_en_el_central`) si lo está o si el paciente todavía es provisorio."""
    if not offline.en_un_nodo():
        return
    if es_provisorio(paciente_id):
        raise SoloEnElCentral(MENSAJE_PROVISORIO)
    offline.exigir_internet(MENSAJE_SIN_CONEXION, MENSAJE_DEL_CENTRAL)


def exigir_sin_id_propio(paciente_id: str | None) -> None:
    """En un nodo, el número del paciente no se elige: lo da el nodo (provisorio) y lo confirma el central."""
    if offline.en_un_nodo() and paciente_id is not None:
        raise SoloEnElCentral(MENSAJE_ID_PROPIO)


# ── En el central: validar ───────────────────────────────────────────────────


def _texto(datos: Mapping, campo: str, operacion, *, obligatorio: bool = False) -> str | None:
    valor = datos.get(campo)
    if valor is None:
        if obligatorio:
            raise AltaDePacienteInvalida(f"el alta del nodo {operacion.node_id} no trae {campo}")
        return None
    if not isinstance(valor, str):
        raise AltaDePacienteInvalida(f"{campo} {valor!r} del alta del nodo {operacion.node_id} no es un texto")
    valor = valor.strip()
    if obligatorio and not valor:
        raise AltaDePacienteInvalida(f"el alta del nodo {operacion.node_id} no trae {campo}")
    if len(valor) > _LARGOS.get(campo, 10_000_000):
        raise AltaDePacienteInvalida(
            f"{campo} del alta del nodo {operacion.node_id} pasa de {_LARGOS[campo]} caracteres"
        )
    return valor or None


def _fecha(datos: Mapping, campo: str, operacion, *, con_zona: bool) -> date | datetime | None:
    crudo = datos.get(campo)
    if crudo is None:
        return None
    try:
        valor = datetime.fromisoformat(crudo) if con_zona else date.fromisoformat(crudo)
    except (TypeError, ValueError) as exc:
        raise AltaDePacienteInvalida(f"{campo} {crudo!r} no es una fecha ISO 8601") from exc
    if con_zona and valor.tzinfo is None:
        raise AltaDePacienteInvalida(f"{campo} {crudo!r} no trae zona horaria")
    return valor


def _datos_de_alta(operacion) -> dict:
    """Valida el payload de `paciente.alta` y lo devuelve con los tipos de Python."""
    from libraedge.mapeo import es_provisorio_de_texto

    if operacion.operation_type != TIPO_PACIENTE_ALTA:
        raise AltaDePacienteInvalida(f"se esperaba {TIPO_PACIENTE_ALTA}, llegó {operacion.operation_type!r}")
    if operacion.schema_version != offline.SCHEMA_VERSION:
        raise AltaDePacienteInvalida(
            f"schema {operacion.schema_version} de {TIPO_PACIENTE_ALTA} desconocido (se entiende "
            f"{offline.SCHEMA_VERSION})"
        )
    datos = operacion.payload
    if datos.get("version") != VERSION:
        raise AltaDePacienteInvalida(
            f"versión {datos.get('version')!r} de los datos de {TIPO_PACIENTE_ALTA} desconocida (se entiende {VERSION})"
        )
    id_nodo = datos.get("paciente_id")
    if not es_provisorio_de_texto(id_nodo):
        raise AltaDePacienteInvalida(
            f"el paciente_id {id_nodo!r} del alta del nodo {operacion.node_id} no es un id provisorio (un texto "
            "`-N`): el nodo sólo sube altas con id provisorio"
        )
    activo = datos.get("active", True)
    if not isinstance(activo, bool):
        raise AltaDePacienteInvalida(f"active {activo!r} del alta del nodo {operacion.node_id} no es un booleano")
    return {
        "paciente_id": id_nodo,
        "name": _texto(datos, "name", operacion, obligatorio=True),
        "phone": _texto(datos, "phone", operacion),
        "email": _texto(datos, "email", operacion),
        "active": activo,
        "dni": _texto(datos, "dni", operacion),
        "birth_date": _fecha(datos, "birth_date", operacion, con_zona=False),
        "cuit": _texto(datos, "cuit", operacion),
        "condicion_iva": _texto(datos, "condicion_iva", operacion),
        "creada_at": _fecha(datos, "creada_at", operacion, con_zona=True),
    }


# ── En el central: la misma persona ──────────────────────────────────────────

_NO_ALFANUMERICO = re.compile(r"[^0-9A-Za-z]")


def clave_documento(valor: str | None) -> str:
    """Un DNI para comparar: sin puntos, guiones ni espacios, en mayúsculas. Vacío si no hay."""
    return _NO_ALFANUMERICO.sub("", valor or "").upper()


def _clave_nombre(valor: str | None) -> str:
    return " ".join((valor or "").lower().split())


def _es_la_misma_persona(existente: Mapping, datos: Mapping) -> bool:
    """Para el reintento de un alta ya mapeada: el DNI decide si los dos lo traen; si no, el nombre."""
    a, b = clave_documento(existente["dni"]), clave_documento(datos["dni"])
    if a and b:
        return a == b
    return _clave_nombre(existente["name"]) == _clave_nombre(datos["name"])


def _paciente_por_dni(conn, dni: str) -> str | None:
    """El paciente **del central** con ese DNI, o `None`. Prefiere uno activo; entre varios, el más viejo."""
    fila = conn.execute(
        """SELECT p.id FROM patients p JOIN agenda_clients c ON c.id = p.id
            WHERE regexp_replace(upper(p.dni), '[^0-9A-Z]', '', 'g') = ? AND substr(p.id, 1, 1) <> '-'
            ORDER BY c.active DESC, p.created_at ASC NULLS LAST, p.id ASC LIMIT 1""",
        (clave_documento(dni),),
    ).fetchone()
    return None if fila is None else fila[0]


def _paciente_mapeado(conn, id_central: str) -> dict | None:
    fila = conn.execute(
        "SELECT p.id, c.name, p.dni FROM patients p JOIN agenda_clients c ON c.id = p.id WHERE p.id = ?",
        (id_central,),
    ).fetchone()
    return None if fila is None else {"id": fila[0], "name": fila[1], "dni": fila[2]}


def _siguiente_numero(conn) -> int:
    """El próximo número de paciente, del mismo contador que usa `PatientRepository` (`patient_sequences`).

    `UPDATE ... RETURNING` toma el candado de la fila: dos altas simultáneas no reciben el mismo número. La primera vez
    el contador se crea partiendo del `p-NNN` más alto que ya exista."""
    for _ in range(2):
        fila = conn.execute(
            "UPDATE patient_sequences SET last = last + 1 WHERE name = ? RETURNING last", (SERIE_PACIENTE,),
        ).fetchone()
        if fila is not None:
            return int(fila[0])
        usados = [
            int(m.group(1)) for (i,) in conn.execute("SELECT id FROM patients").fetchall()
            if (m := _ID_GENERADO.match(i))
        ]
        conn.execute(
            "INSERT INTO patient_sequences (name, last) VALUES (?, ?) ON CONFLICT (name) DO NOTHING",
            (SERIE_PACIENTE, max(usados, default=0)),
        )
    raise PacienteDelNodoError("no se pudo iniciar la serie de números de paciente")


def _insertar(conn, datos: Mapping) -> str:
    """Crea la persona y su ficha con el próximo `p-NNN` libre; devuelve el id."""
    for _ in range(INTENTOS_DE_ID):
        nuevo = f"{PREFIJO_ID}{_siguiente_numero(conn):03d}"
        tomado = conn.execute(
            "INSERT INTO agenda_clients (id, name, phone, email, active) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (id) DO NOTHING RETURNING id",
            (nuevo, datos["name"], datos["phone"], datos["email"], datos["active"]),
        ).fetchone()
        if tomado is None:
            continue   # alguien lo escribió a mano (`p-007`): se toma el siguiente en vez de fallar el alta
        conn.execute(
            "INSERT INTO patients (id, dni, birth_date, cuit, condicion_iva, created_at) "
            "VALUES (?, ?, ?, ?, ?, COALESCE(?, now()))",
            (nuevo, datos["dni"], datos["birth_date"], datos["cuit"], datos["condicion_iva"], datos["creada_at"]),
        )
        return nuevo
    raise PacienteDelNodoError("no hay un número de paciente libre")


# ── En el central: aplicar ───────────────────────────────────────────────────


def aplicar_paciente_alta(conn, operacion) -> None:
    """Aplica `paciente.alta` en el central: une al paciente con el que ya tiene ese DNI o lo crea con su `p-NNN`, y anota
    los mapeos `(nodo, 'agenda_clients' | 'patients', id provisorio) -> id`. Todo en la transacción del receptor: o queda
    el paciente y sus mapeos, o ninguno. Idempotente.

    Los errores son `ValueError` (revisión manual): un `IntegrityError` ajeno lo leería el receptor como «duplicado»."""
    from libraedge import mapeo

    datos = _datos_de_alta(operacion)
    node_id, id_nodo = operacion.node_id, datos["paciente_id"]

    id_central = mapeo.traducir_id(conn, node_id, TABLA_PACIENTES, id_nodo, exigir=False)
    if id_central is not None:
        # Entregada otra vez (el outbox entrega al menos una vez). Si el paciente mapeado no es esta persona, el nodo
        # reusó un id provisorio (una PC reemplazada con el mismo `node_id`): revisión manual, no se pisa nada.
        existente = _paciente_mapeado(conn, id_central)
        if existente is None:
            raise PacienteDelNodoError(
                f"el alta del paciente {id_nodo} del nodo {node_id} ya estaba mapeada al {id_central} "
                "y ese paciente ya no existe"
            )
        if not _es_la_misma_persona(existente, datos):
            raise PacienteDelNodoError(
                f"el nodo {node_id} reusó el id provisorio {id_nodo}: ya estaba mapeado al paciente {id_central} del "
                f"central ({existente['name']!r}) y ahora llega el alta de {datos['name']!r}. Una nota a ese id iría "
                "a otra persona: revisar a mano"
            )
        return

    id_central = _paciente_por_dni(conn, datos["dni"]) if clave_documento(datos["dni"]) else None
    if id_central is not None:
        logger.info(
            "paciente.alta del nodo %s: el paciente provisorio %s es el %s del central (mismo DNI)",
            node_id, id_nodo, id_central,
        )
    else:
        id_central = _insertar(conn, datos)
    try:
        mapeo.anotar_mapeo(conn, node_id, TABLA_CLIENTES, id_nodo, id_central)
        mapeo.anotar_mapeo(conn, node_id, TABLA_PACIENTES, id_nodo, id_central)
    except mapeo.MapeoEnConflicto as exc:
        raise PacienteDelNodoError(str(exc)) from exc


def aplicadores() -> dict[str, Any]:
    """`{operation_type: (conn, operacion) -> None}` de `paciente.alta`, para el despachador del central."""
    return {TIPO_PACIENTE_ALTA: aplicar_paciente_alta}


def registrar_en(despachador):
    """Registra `paciente.alta` en un `libraedge.sync.despacho.Despachador` y lo devuelve. Registrar dos veces un tipo
    falla al arrancar (es la regla del `Despachador`)."""
    for tipo, aplicador in aplicadores().items():
        despachador.registrar(tipo, offline.SCHEMA_VERSION, aplicador)
    return despachador
