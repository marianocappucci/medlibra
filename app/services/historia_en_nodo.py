"""La historia clínica que se carga en un nodo de LibraEdge sin conexión, y su vuelta en el central (ADR-045).

Decisión del humano (2026-10-25): *notas, recetas, pedidos de estudio y consentimientos se cargan sin conexión*. Son
**altas, no ediciones**: cada una es una fila nueva que no se edita nunca (ADR-006, ADR-011, ADR-012 y ADR-014 de este
producto), así que no se pisa con nada de lo que se cargue en la web.

## Por qué no necesitan id provisorio

El id de cada una es un **uuid4 que genera la aplicación** (`str(uuid4())`), no una secuencia de la base: el nodo y el
central no pueden dar el mismo. La fila nace en el nodo con su id definitivo y el central la crea **con el mismo id**
(`INSERT ... ON CONFLICT (id) DO NOTHING`): ni mapeo ni reapuntado. Es lo que las separa de los pacientes
(`pacientes_nodo.py`), que tienen `p-NNN` de un contador. La tabla está en el espejo pero **no** en las de sólo lectura
(`offline.TABLAS_SOLO_LECTURA`): el nodo la escribe; cuando el central la crea, la fila baja por el espejo idéntica.

Lo único que puede ser provisorio es el **paciente** al que apuntan (`patient_id`). El central lo traduce con el mapeo de
`patients` (`traducir_id`): si el alta del paciente quedó en revisión manual, la nota se rechaza (`SinMapeo`, un
`ValueError`) en vez de quedar atada a nadie, y se reintenta al resolver el alta. **El orden lo da el outbox**: las
operaciones de un nodo se aplican en el orden en que se encolaron (ADR-020 de libraedge), y el alta del paciente se
encola antes que su primera nota.

## Las operaciones

| `operation_type` | Qué sube | Tablas |
|---|---|---|
| `nota.alta` | una nota de evolución | `clinical_notes` |
| `receta.alta` | una receta con sus medicamentos | `prescriptions`, `prescription_items` |
| `pedido_estudio.alta` | un pedido de estudios con sus ítems | `study_orders`, `study_order_items` |
| `consentimiento.alta` | un consentimiento informado | `consents` |

`schema_version = 1`, `aggregate_type` = `nota`, `receta`, `pedido_estudio`, `consentimiento`. Payload `version 1`:
`{"version", "id", "fila": {columna: valor}, "hijas": {tabla: [ {columna: valor} ]}}`. Los instantes, ISO 8601 con zona.
La encola `encolar_alta`, **en la misma transacción** que la fila: no queda una nota sin su operación.

## Lo que el nodo no hace con la historia clínica

- **Borrar** una nota, una receta, un pedido o un consentimiento: no sube (409 `solo_en_el_central`). Es de admin y para
  corregir un error de carga; se hace en la web.
- **Cargar el resultado de un estudio** (`study_results`) y los **documentos adjuntos**: los segundos son archivos del
  disco del central y los primeros no están en esta decisión. 409.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .. import offline


@dataclass(frozen=True)
class Columna:
    """Una columna que viaja en la operación. `tipo`: `texto`, `entero` o `instante`."""

    nombre: str
    tipo: str = "texto"
    largo: int | None = None
    nulable: bool = False


@dataclass(frozen=True)
class Hija:
    """Las filas que cuelgan de la principal con una clave foránea (`prescription_items.prescription_id`)."""

    tabla: str
    clave: str
    columnas: tuple[Columna, ...]


@dataclass(frozen=True)
class AltaClinica:
    tipo: str
    agregado: str
    tabla: str
    columnas: tuple[Columna, ...]
    hijas: tuple[Hija, ...] = ()
    #: La columna que apunta al paciente (la única que puede traer un id provisorio).
    paciente: str = "patient_id"


VERSION = 1

_ID = Columna("id", largo=100)
_PACIENTE = Columna("patient_id", largo=100)
_CUANDO = Columna("created_at", "instante")
_AUTOR = Columna("author", largo=200)

NOTA = AltaClinica(
    tipo="nota.alta", agregado="nota", tabla="clinical_notes",
    columnas=(_ID, _PACIENTE, _CUANDO, _AUTOR, Columna("text")),
)
RECETA = AltaClinica(
    tipo="receta.alta", agregado="receta", tabla="prescriptions",
    columnas=(_ID, _PACIENTE, _CUANDO, _AUTOR),
    hijas=(Hija("prescription_items", "prescription_id", (
        _ID, Columna("position", "entero"), Columna("medication", largo=200), Columna("dosage", largo=200),
        Columna("instructions", nulable=True),
    )),),
)
PEDIDO_DE_ESTUDIO = AltaClinica(
    tipo="pedido_estudio.alta", agregado="pedido_estudio", tabla="study_orders",
    columnas=(_ID, _PACIENTE, _CUANDO, _AUTOR),
    hijas=(Hija("study_order_items", "order_id", (
        _ID, Columna("position", "entero"), Columna("study_type", largo=200), Columna("reason", nulable=True),
    )),),
)
CONSENTIMIENTO = AltaClinica(
    tipo="consentimiento.alta", agregado="consentimiento", tabla="consents",
    columnas=(
        _ID, _PACIENTE, _CUANDO, _AUTOR, Columna("procedure", largo=300), Columna("granted_by", largo=200),
        Columna("text"),
    ),
)

ALTAS = (NOTA, RECETA, PEDIDO_DE_ESTUDIO, CONSENTIMIENTO)
TIPOS = tuple(a.tipo for a in ALTAS)


class AltaClinicaInvalida(ValueError):
    """El payload de una alta clínica no se entiende o trae algo que el central no puede escribir. Es un `ValueError` a
    propósito: el receptor de LibraEdge la manda a revisión manual y el nodo no traba la cola (ADR-020 de libraedge)."""


# ── En el nodo ───────────────────────────────────────────────────────────────


def _como_viaja(valor: Any) -> Any:
    return valor.isoformat() if isinstance(valor, datetime) else valor


def _fila(modelo: Any, columnas: tuple[Columna, ...]) -> dict:
    return {c.nombre: _como_viaja(getattr(modelo, c.nombre)) for c in columnas}


def encolar_alta(sesion, alta: AltaClinica, fila: Any) -> bool:
    """Encola la operación de `alta` **en la transacción de `sesion`**, con las columnas de `fila` (el modelo ya
    agregado a la sesión) y las de sus hijas (`fila.items`). Devuelve si encoló: **fuera de un nodo no hace nada** y
    devuelve `False`, así los repositorios la llaman siempre sin preguntar antes.

    Hace `flush` antes: la operación sale con lo que la base va a guardar."""
    if not offline.en_un_nodo():
        return False
    sesion.flush()
    hijas = {}
    for hija in alta.hijas:
        hijas[hija.tabla] = [_fila(item, hija.columnas) for item in fila.items]
    offline.encolar_operacion(sesion, alta.tipo, alta.agregado, fila.id, {
        "version": VERSION, "id": fila.id, "fila": _fila(fila, alta.columnas), "hijas": hijas,
    })
    return True


def exigir_central_para_resultados() -> None:
    """Cargar o borrar el resultado de un estudio no se hace en el nodo: no sube."""
    offline.exigir_internet(
        "Sin conexión: los resultados de los estudios se cargan desde la web, cuando vuelva la conexión.",
        "Los resultados de los estudios se cargan desde la web: desde esta PC sólo se pide el estudio.",
    )


# ── En el central: validar ───────────────────────────────────────────────────


def _valor(dato: Any, columna: Columna, operacion) -> Any:
    donde = f"{columna.nombre} del alta del nodo {operacion.node_id}"
    if dato is None:
        if columna.nulable:
            return None
        raise AltaClinicaInvalida(f"{donde} no puede faltar")
    if columna.tipo == "entero":
        if isinstance(dato, bool) or not isinstance(dato, int):
            raise AltaClinicaInvalida(f"{donde} {dato!r} no es un entero")
        return dato
    if columna.tipo == "instante":
        try:
            fecha = datetime.fromisoformat(dato)
        except (TypeError, ValueError) as exc:
            raise AltaClinicaInvalida(f"{donde} {dato!r} no es una fecha ISO 8601") from exc
        if fecha.tzinfo is None:
            # Sin zona se leería como UTC: la nota de las 20:00 quedaría a las 17:00.
            raise AltaClinicaInvalida(f"{donde} {dato!r} no trae zona horaria")
        return fecha
    if not isinstance(dato, str) or (not columna.nulable and not dato.strip()):
        raise AltaClinicaInvalida(f"{donde} no es un texto")
    if columna.largo is not None and len(dato) > columna.largo:
        raise AltaClinicaInvalida(f"{donde} pasa de {columna.largo} caracteres")
    return dato


def _fila_valida(datos: Any, columnas: tuple[Columna, ...], operacion) -> dict:
    if not isinstance(datos, Mapping):
        raise AltaClinicaInvalida(f"el alta del nodo {operacion.node_id} no trae sus datos")
    return {c.nombre: _valor(datos.get(c.nombre), c, operacion) for c in columnas}


def _validar(alta: AltaClinica, operacion) -> tuple[dict, dict[str, list[dict]]]:
    if operacion.operation_type != alta.tipo:
        raise AltaClinicaInvalida(f"se esperaba {alta.tipo}, llegó {operacion.operation_type!r}")
    if operacion.schema_version != offline.SCHEMA_VERSION:
        raise AltaClinicaInvalida(
            f"schema {operacion.schema_version} de {alta.tipo} desconocido (se entiende {offline.SCHEMA_VERSION})"
        )
    datos = operacion.payload
    if datos.get("version") != VERSION:
        raise AltaClinicaInvalida(
            f"versión {datos.get('version')!r} de los datos de {alta.tipo} desconocida (se entiende {VERSION})"
        )
    fila = _fila_valida(datos.get("fila"), alta.columnas, operacion)
    hijas = {}
    for hija in alta.hijas:
        crudas = (datos.get("hijas") or {}).get(hija.tabla)
        if not isinstance(crudas, list) or not crudas:
            raise AltaClinicaInvalida(f"el alta del nodo {operacion.node_id} no trae {hija.tabla}")
        hijas[hija.tabla] = [_fila_valida(cruda, hija.columnas, operacion) for cruda in crudas]
    return fila, hijas


# ── En el central: aplicar ───────────────────────────────────────────────────


def _insertar_una_vez(conn, tabla: str, valores: Mapping[str, Any]) -> bool:
    """`INSERT ... ON CONFLICT (id) DO NOTHING`: devuelve si fue **ésta** la que puso la fila."""
    columnas = list(valores)
    fila = conn.execute(
        f"INSERT INTO {tabla} ({', '.join(columnas)}) VALUES ({', '.join('?' for _ in columnas)}) "
        "ON CONFLICT (id) DO NOTHING RETURNING id",
        tuple(valores[c] for c in columnas),
    ).fetchone()
    return fila is not None


def aplicar_alta(alta: AltaClinica) -> Callable[[Any, Any], None]:
    """El aplicador de `alta.tipo` para el despachador del central: crea la fila **con el mismo id** que le puso el nodo,
    con el paciente traducido, en la transacción del receptor. **Idempotente**: la misma operación otra vez no hace
    nada. Un paciente que no existe o un alta de paciente sin aplicar es un `ValueError` (revisión manual)."""

    def aplicador(conn, operacion) -> None:
        from libraedge import mapeo

        fila, hijas = _validar(alta, operacion)
        paciente = mapeo.traducir_id(conn, operacion.node_id, "patients", fila[alta.paciente])
        existe = conn.execute("SELECT 1 FROM patients WHERE id = ?", (paciente,)).fetchone()
        if existe is None:
            raise AltaClinicaInvalida(
                f"el paciente {paciente!r} del alta {alta.tipo} del nodo {operacion.node_id} no existe en el central"
            )
        fila[alta.paciente] = paciente
        if not _insertar_una_vez(conn, alta.tabla, fila):
            return   # ya estaba (el outbox entrega al menos una vez): sus hijas también
        for hija in alta.hijas:
            for item in hijas[hija.tabla]:
                if not _insertar_una_vez(conn, hija.tabla, {**item, hija.clave: fila["id"]}):
                    raise AltaClinicaInvalida(
                        f"{hija.tabla} {item['id']} del alta {alta.tipo} del nodo {operacion.node_id} ya existe "
                        "con otra fila: un uuid repetido"
                    )

    return aplicador


def registrar_en(despachador):
    """Registra las cuatro operaciones en un `libraedge.sync.despacho.Despachador` y lo devuelve."""
    for alta in ALTAS:
        despachador.registrar(alta.tipo, offline.SCHEMA_VERSION, aplicar_alta(alta))
    return despachador
