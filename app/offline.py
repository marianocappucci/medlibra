"""La costura de MedLibra con LibraEdge: lo único del nodo sin conexión que es de este producto (ADR-045).

El nodo es la instancia de MedLibra que corre en la PC del consultorio y sincroniza con el central (el VPS) por
LibraEdge. Sin internet, en el consultorio se **consulta la agenda y la historia clínica completa, se atiende un turno
ya dado** (en curso, atendido o «no vino»), se **cargan notas, recetas, pedidos de estudio y consentimientos**, se
**anota la demanda espontánea** y se **da de alta un paciente** con número provisorio (decisiones del humano,
2026-10-21 y 2026-10-25). Todo lo genérico es de los motores: el aprovisionamiento es de LibraEdge y atender un turno
sin conexión es de LibraGenda (`libragenda.atencion_en_nodo`, ADR-019). Lo que queda acá es declarativo.

MedLibra **no factura y no tiene caja**: al completar un turno manda la consulta y sus pagos a ContaLibra (ADR-035 y
ADR-036). Sin conexión eso **no se hace en la PC**: el turno atendido sube como `turno.atendido` con los pagos en
`extra`, y **el central manda a ContaLibra al aplicarlo** (`app/services/atencion_nodo.py`). Así la PC no guarda el
token de ContaLibra y no pueden salir dos envíos.

| Pieza | Qué aporta este producto |
|---|---|
| `aprovisionamiento` | las tablas de referencia (el reparto de autoridad), las de sólo lectura y las altas en el nodo |
| `encolar_operacion` | la costura de LibraGenda y de los altas del producto con el outbox de LibraEdge |
| `CONEXION` / `en_linea()` | si el nodo ve al central (decide qué 409 se contesta) |
| `solo_en_el_central` | la guarda de lo que el nodo no hace |

## Quién manda sobre qué

El central es la autoridad de los **maestros** (sedes, profesionales, prestaciones, precios, bloques de agenda,
consultorios, módulos, feriados) y de **los turnos**: bajan al nodo por el espejo y el nodo no los escribe (la guarda
de LibraEdge, ADR-019, lo rechaza). El nodo da de alta, con id propio, sólo lo que **no se pisa**:

- **los pacientes** (`agenda_clients` y `patients`): id provisorio de texto `"-N"`; el central asigna el `p-NNN` y, si ya
  existía con ese DNI, el paciente se une a su ficha (ADR-026 de LibraEdge, `pacientes_nodo.py`);
- **notas, recetas, pedidos de estudio y consentimientos**: filas nuevas con un uuid propio (no chocan con nada), que
  suben como `nota.alta`, `receta.alta`, `pedido_estudio.alta` y `consentimiento.alta` (`historia_en_nodo.py`);
- **la demanda espontánea** (`walkins`): `walkin.registrado` y `walkin.estado` (`walkins_nodo.py`);
- **la atención de un turno**: la fila propia del nodo (`agenda_node_attendances`) y `turno.atendido`.

## Identidad: `LIBRAEDGE_NODE_ID` (y `MEDLIBRA_EDGE_NODE_ID`, por la regla del motor)

`nodo()` es `libraedge.identidad.nodo_actual("MEDLIBRA")`. Es la **identidad** del nodo y la escribe el instalador.
LibraEdge está incluido en todos los planes (libraedge ADR-014): no hay guarda comercial al registrar (`sin_guarda`).

## Aprovisionar (en el central)

    LIBRAEDGE_APROVISIONAMIENTO=app.offline:aprovisionamiento libraedge-central nodo publicar
    libraedge-central nodo sucursales | registrar <node_id> --sucursal <id o nombre> | estado | dar-de-baja <id>
    LIBRAEDGE_DESPACHADOR=app.routers.sincronizacion_offline:despachador libraedge-central revision listar ...
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from libracore.nodo_offline import (
    VARIABLE_ESTADO,
    ConexionDelNodo,
    SinConexion,
    SoloEnElCentral,
    esta_en_linea,
    guarda_solo_en_el_central,
)
from libraedge.altas import AltaEnNodo
from libraedge.identidad import nodo_actual

#: El prefijo de las variables del producto (`MEDLIBRA_DATABASE_URL`, `MEDLIBRA_EDGE_NODE_ID`).
PREFIJO = "MEDLIBRA"

#: El `schema_version` de las operaciones propias de MedLibra (el de LibraGenda es el mismo).
SCHEMA_VERSION = 1

# ── Qué se espeja ───────────────────────────────────────────────────────────────────────────────────────────────────

#: El reparto de autoridad: qué tablas manda el central y el nodo espeja. **Sólo los nombres**: la clave la lee
#: LibraEdge de la base. El porqué de cada una, en DECISIONS.md ADR-045.
#:
#: 🔴 NO están, a propósito (cada una con su motivo en `tests/test_nodo_aprovisionamiento.py`, `EXCLUIDAS`):
#: - lo que sólo existe en el central o lo genera el nodo y no se espeja: `agenda_node_attendances` (la atención del
#:   nodo sube como `turno.atendido`), `patient_sequences` (el contador del `p-NNN` es del central), `actividad_log`
#:   y `auth_log` (cada punta lleva el suyo);
#: - los secretos y la configuración del central: `secretos_instancia`, `smtp_settings`, `demo_codigos`, los tokens de
#:   recuperación de contraseña y el anti-replay del captcha;
#: - todo LibraCore (caja, facturas, ARCA, ventas): MedLibra no factura, manda la consulta a ContaLibra.
TABLAS_DE_REFERENCIA = frozenset({
    # libraauth: la sesión y el gate de Términos. Los usuarios del nodo son los del central (libraauth ADR-027).
    "usuarios", "aceptaciones_terminos",
    # LibraGenda: el catálogo y los turnos. `agenda_clients` baja y además el nodo da sus pacientes provisorios.
    "branches", "resources", "services", "availability", "availability_exceptions", "time_blocks", "holidays",
    "agenda_policies", "appointments", "appointment_resources", "appointment_transitions", "deposits",
    "agenda_clients", "agenda_applied_attendances",
    # MedLibra, maestros y configuración.
    "medlibra_modulos", "business_settings", "branch_contacts", "branch_hours", "consultorios", "agenda_blocks",
    "service_prices", "resource_service_prices", "service_iva_rates", "envios_a_contalibra",
    # MedLibra, la ficha del paciente y la historia clínica. `patients` y las filas que el nodo carga (notas,
    # recetas, estudios, consentimientos, demanda espontánea) bajan y además el nodo da las suyas.
    "patients", "clinical_notes", "prescriptions", "prescription_items", "study_orders", "study_order_items",
    "study_results", "consents", "clinical_documents", "walkins",
})

#: Los maestros que el nodo **no escribe**: LibraEdge les instala una guarda en la base del nodo y un intento de
#: escribirlos da un error claro en vez de pisarse con el espejo en el próximo ciclo. No están `usuarios` y
#: `aceptaciones_terminos` (`espejar_usuario` hace un upsert idempotente) ni las filas que el nodo carga con un uuid
#: propio (notas, recetas, estudios, consentimientos y demanda espontánea: no se pisan con nada del central).
#:
#: Sí están `agenda_clients` y `patients`, que tienen alta en el nodo: la guarda deja pasar las filas con id negativo
#: (`"-N"`) y sigue rechazando todo lo que toque la ficha de un paciente del central (ADR-021 de LibraEdge, punto 7).
#: Los turnos (`appointments`) están: la atención del nodo es una fila propia, no una edición del turno.
TABLAS_SOLO_LECTURA = frozenset({
    "branches", "resources", "services", "availability", "availability_exceptions", "time_blocks", "holidays",
    "agenda_policies", "appointments", "appointment_resources", "appointment_transitions", "deposits",
    "agenda_clients", "agenda_applied_attendances",
    "medlibra_modulos", "business_settings", "branch_contacts", "branch_hours", "consultorios", "agenda_blocks",
    "service_prices", "resource_service_prices", "service_iva_rates", "envios_a_contalibra",
    "patients", "study_results", "clinical_documents",
})

#: Los pacientes se dan de alta en el nodo con un id provisorio de **texto** (`"-N"`, libraedge ADR-026). Son dos
#: tablas y las dos declaran su alta: `patients.id` es a la vez clave primaria y clave foránea a `agenda_clients.id`, y
#: lo que cuelga de `patients` (notas, recetas, estudios, consentimientos, documentos) tiene que reapuntarse por **su**
#: mapeo. Lo que referencia a una u otra con una clave foránea (`walkins.client_id`, `clinical_notes.patient_id`...) lo
#: encuentra LibraEdge solo en el catálogo; no hay referencias sin FK que declarar.
ALTAS_EN_EL_NODO = (
    AltaEnNodo("agenda_clients", id_de_texto=True),
    AltaEnNodo("patients", id_de_texto=True),
)


# ── La identidad y la conexión del nodo ─────────────────────────────────────────────────────────────────────────────


def nodo() -> str | None:
    """El id de este nodo, o `None` si la instancia no es un nodo (el central, o una instalación común).

    Se lee en cada llamada: activar el nodo no exige reiniciar nada y la suite no depende del orden de los tests."""
    return nodo_actual(PREFIJO)


def en_un_nodo() -> bool:
    return nodo() is not None


def en_linea() -> bool:
    """Si el nodo ve al central: lo que dice el archivo de estado del proceso del nodo (`LIBRAEDGE_ESTADO`).

    Es la de libracore (ADR-074): el último ciclo sincronizó y la última sincronización buena es reciente. Sin archivo,
    viejo o ilegible, sin conexión. La ruta se lee en cada llamada."""
    return esta_en_linea((os.environ.get(VARIABLE_ESTADO) or "").strip() or None)


#: Lo que LibraCore pregunta (la barra del pie, `/api/estado-del-sistema`). Fuera de un nodo, nada cambia. Las dos
#: funciones se llaman por nombre en cada pregunta (no se atan al construirla): así un test puede cambiarlas.
CONEXION = ConexionDelNodo(nodo=lambda: nodo(), en_linea=lambda: en_linea())

#: Lo que el nodo no hace: `Depends(solo_en_el_central)` contesta 409 `solo_en_el_central` en un nodo y no hace nada
#: en el central ni en una instalación común.
solo_en_el_central = guarda_solo_en_el_central(nodo=lambda: nodo())

_LECTURAS = frozenset({"GET", "HEAD", "OPTIONS"})

MENSAJE_TURNOS_SOLO_EN_EL_CENTRAL = (
    "Los turnos se dan, se mueven y se cancelan desde la web. Desde esta PC se atienden los que ya están dados."
)
MENSAJE_TURNOS_SIN_CONEXION = (
    "Sin conexión: los turnos se dan, se mueven y se cancelan desde la web, cuando vuelva la conexión."
)
MENSAJE_DOCUMENTOS_SIN_CONEXION = (
    "Sin conexión: los documentos adjuntos (estudios escaneados, informes) se ven y se suben sólo con internet."
)
MENSAJE_DOCUMENTOS_SOLO_EN_EL_CENTRAL = (
    "Los documentos adjuntos (estudios escaneados, informes) se ven y se suben desde la web: esta PC no tiene los archivos."
)
MENSAJE_BORRAR_SOLO_EN_EL_CENTRAL = (
    "Borrar historia clínica se hace desde la web: desde esta PC sólo se agrega."
)


def escritura_solo_en_el_central(request: Request) -> None:
    """Como `solo_en_el_central`, pero **sólo para lo que escribe**: las lecturas pasan. Es lo que se le pone a un
    router entero cuyos datos manda el central (maestros, precios, configuración): el nodo los lee del espejo y no los
    cambia."""
    if request.method not in _LECTURAS:
        solo_en_el_central()


def _en_linea_seguro() -> bool:
    try:
        return bool(en_linea())
    except Exception:  # noqa: BLE001 - ante la duda, sin conexión
        return False


def exigir_internet(mensaje_sin_conexion: str, mensaje_solo_en_el_central: str) -> None:
    """En un nodo, lo que sólo se hace con internet (los turnos, los documentos adjuntos): `SinConexion` (409
    `sin_conexion`) si el nodo no está en línea y `SoloEnElCentral` (409 `solo_en_el_central`) si lo está: el nodo no
    tiene cómo hacerlo ni aun con conexión, se hace desde la web. En el central, no hace nada."""
    if not en_un_nodo():
        return
    if _en_linea_seguro():
        raise SoloEnElCentral(mensaje_solo_en_el_central)
    raise SinConexion(mensaje_sin_conexion)


def exigir_central_para_turnos() -> None:
    """Dar, confirmar, mover o cancelar un turno no se hace en el nodo (decisión del humano, 2026-10-21): 409."""
    exigir_internet(MENSAJE_TURNOS_SIN_CONEXION, MENSAJE_TURNOS_SOLO_EN_EL_CENTRAL)


def exigir_central_para_documentos() -> None:
    """Los documentos clínicos adjuntos son archivos del disco del central (`MEDLIBRA_DOCUMENTS_DIR`): LibraEdge espeja
    filas, no archivos. Se ven y se suben sólo con internet (decisión del humano, 2026-10-25)."""
    exigir_internet(MENSAJE_DOCUMENTOS_SIN_CONEXION, MENSAJE_DOCUMENTOS_SOLO_EN_EL_CENTRAL)


def exigir_central_para_borrar() -> None:
    """Borrar una nota, una receta, un pedido, un consentimiento o un documento no sube al central: en el nodo, 409."""
    if en_un_nodo():
        raise SoloEnElCentral(MENSAJE_BORRAR_SOLO_EN_EL_CENTRAL)


# ── Encolar una operación propia ────────────────────────────────────────────────────────────────────────────────────


def conexion_de_la_sesion(sesion):
    """La conexión del motor (`?` como marcador, filas por posición) **sobre la misma transacción** de la sesión de
    SQLAlchemy. El outbox de LibraEdge se escribe con esa interfaz, y tiene que entrar en la transacción de la nota, el
    paciente o la atención: sin esto serían dos conexiones y una nota podría quedar sin su operación, o al revés.

    No se cierra ni se commitea: es de la sesión."""
    from libracore.db._postgres import ConnectionWrapper

    return ConnectionWrapper(sesion.connection().connection.driver_connection)


def _ahora_utc() -> str:
    return datetime.now(UTC).isoformat()


def encolar_operacion(sesion, tipo: str, agregado: str, id_local: Any, payload: Mapping[str, Any]) -> None:
    """Encola `tipo` en el outbox de este nodo, **en la transacción de `sesion`** (no confirma).

    Es el contrato de ADR-025 de LibraEdge: `operation_id = <nodo>:<secuencia>`, `aggregate_id =
    <nodo>:<agregado>:<id local>`, la secuencia es una sola por nodo, así que el central recibe las operaciones en el
    orden en que ocurrieron (el alta del paciente antes que su nota). Es también la firma que LibraGenda espera en
    `AtencionesEnNodo.encolar`. Levanta `RuntimeError` fuera de un nodo: encolar en el central dejaría una operación que
    nadie sube."""
    from libraedge.db.repository import NodeRepository
    from libraedge.domain.sync import OutboxOperation

    node_id = nodo()
    if node_id is None:
        raise RuntimeError("Encolar una operación es del nodo: esta instancia no es un nodo de LibraEdge.")
    repo = NodeRepository(conexion_de_la_sesion(sesion))
    secuencia = repo.next_sequence(commit=False)
    repo.enqueue_operation(OutboxOperation(
        operation_id=f"{node_id}:{secuencia}", node_id=node_id, sequence=secuencia, operation_type=tipo,
        aggregate_type=agregado, aggregate_id=f"{node_id}:{agregado}:{id_local}", occurred_at=_ahora_utc(),
        schema_version=SCHEMA_VERSION, payload=dict(payload),
    ), commit=False)


def configurar() -> None:
    """Enchufa lo que se da en el nodo a su outbox: la atención de un turno (`libragenda.atencion_en_nodo`).

    **Igual en el nodo y en el central**, una vez al armar la app (`create_app` la llama): fuera de un nodo `nodo()` es
    `None` y LibraGenda no encola nada ni deja atender. Los altas de pacientes, historia clínica y demanda espontánea no
    necesitan configuración: preguntan `offline.nodo()` en cada alta."""
    from libragenda import atencion_en_nodo

    atencion_en_nodo.configurar(atencion_en_nodo.AtencionesEnNodo(nodo=nodo, encolar=encolar_operacion))


# ── El aprovisionamiento del central ────────────────────────────────────────────────────────────────────────────────


def _conectar():
    """La base de la instancia, para el CLI de LibraEdge (que corre sin la app): la misma URL que arma `app/asgi.py`.
    En MedLibra el dominio y LibraCore son la misma base (ADR-044)."""
    from libracore.db.core import conectar
    from libracore.db.url_de_instancia import url_de_instancia

    return conectar(url_de_instancia("medlibra", requerida=True))


def nodos_del_central() -> list[dict]:
    """Los nodos registrados en esta instancia: la misma lista que «Sucursal sin internet»."""
    from libracore.db.core import get_connection
    from libraedge.pantalla_del_central import nodos_de_la_instancia

    with get_connection() as conn:
        return nodos_de_la_instancia(conn, [])


def listar_sucursales(conn) -> list[dict]:
    """Las sedes a las que se puede atar un nodo: las `branches` de LibraGenda (de ellas cuelgan los profesionales, los
    consultorios y los precios)."""
    filas = conn.execute("SELECT id, name, active FROM branches ORDER BY name").fetchall()
    return [{"id": f[0], "nombre": f[1], "activa": bool(f[2])} for f in filas]


def _aprovisionamiento():
    from libraedge.aprovisionamiento import Aprovisionamiento, sin_guarda

    return Aprovisionamiento(
        prefijo=PREFIJO, tablas_de_referencia=TABLAS_DE_REFERENCIA, listar_sucursales=listar_sucursales,
        # Sin guarda comercial: LibraEdge está incluido en todos los planes (libraedge ADR-014).
        verificar_alta=sin_guarda, conectar=_conectar,
        tablas_solo_lectura=TABLAS_SOLO_LECTURA, altas_en_nodo=ALTAS_EN_EL_NODO,
    )


#: Lo que el central necesita para aprovisionar los nodos de este producto (`LIBRAEDGE_APROVISIONAMIENTO`).
aprovisionamiento = _aprovisionamiento()
