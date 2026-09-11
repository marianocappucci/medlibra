"""La fila por orden de llegada de un bloque de demanda espontánea.

Ver `app/services/walkins.py` para por qué esto no es un turno de LibraGenda.

🔴 **Registrar una llegada valida el bloque, no sólo su existencia.** Dos
chequeos que parecen burocracia y no lo son:

- **El bloque tiene que ser `espontanea`.** Sobre uno de `turnos` se dan turnos
  con hora; anotar gente en una fila ahí crearía dos maneras simultáneas de
  ocupar la misma franja, cada una ciega a la otra.
- **El día tiene que caer dentro del bloque** — su día de la semana y su
  vigencia. Sin eso se puede anotar gente para un martes en una agenda que sólo
  atiende los lunes, o para después de que la agenda venció: una fila que nadie
  va a llamar nunca.

🔴 **Lo que la pantalla necesita leer también vive acá, y no en los routers de
configuración.** `/agenda-blocks` y `/services` son `admin_only`: el mostrador
—que es quien opera la fila— recibe 403 en los dos. Abrirlos a `staff` le daría
además el alta, la edición y el borrado de la agenda. En vez de eso, este router
(que ya es `staff_or_admin`) sirve una lectura recortada a lo que la fila usa:
qué bloques de demanda espontánea rigen un día y qué prestaciones se pueden
anotar. Ver ADR-038.
"""
from datetime import date, time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from libragenda.catalog_repository import SqlAlchemyCatalogRepository
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from ..dependencies import (
    get_agenda_block_repository,
    get_catalog_repository,
    get_consultorio_repository,
    get_walkin_repository,
)
from ..services.agenda_blocks import AgendaBlockRepository
from ..services.consultorios import ConsultorioRepository
from ..services.husos import zona_del_recurso
from ..services.walkins import (
    ATENDIDO,
    CANCELADO,
    EN_ATENCION,
    TransicionInvalida,
    WalkinRepository,
)
from ._instantes import InstanteUTC

router = APIRouter(tags=["walkins"])


class LlegadaCreate(BaseModel):
    client_id: str
    service_id: str
    #: El día de la fila. Se manda explícito y no se toma de `today()`: la
    #: secretaria puede estar anotando la fila de mañana, y "hoy" del servidor
    #: no es necesariamente "hoy" de la sede.
    day: date


class WalkinOut(BaseModel):
    id: str
    block_id: str
    day: date
    client_id: str
    service_id: str
    arrival_order: int
    status: str
    created_at: InstanteUTC


class BloqueDeLaFila(BaseModel):
    """Un bloque de demanda espontánea que rige el día pedido, con los nombres
    ya resueltos: quien lo pide no puede leer `/resources` ni `/consultorios`."""

    id: str
    resource_id: str
    profesional: str
    consultorio_id: str
    consultorio: str
    starts_at: time
    ends_at: time
    #: El huso de la sede del profesional. La hora de llegada viaja en UTC
    #: (`InstanteUTC`) y se muestra en la hora de la SEDE, que puede no ser la
    #: de Argentina — la misma separación que la agenda (ADR-028).
    timezone: str


class PrestacionDeLaFila(BaseModel):
    id: str
    name: str


@router.get("/walkins/bloques", response_model=list[BloqueDeLaFila])
def bloques_del_dia(
    day: date,
    blocks: AgendaBlockRepository = Depends(get_agenda_block_repository),
    catalog: SqlAlchemyCatalogRepository = Depends(get_catalog_repository),
    consultorios: ConsultorioRepository = Depends(get_consultorio_repository),
):
    """Dónde se puede armar una fila ese día.

    No filtra por profesional activo, a propósito: lo que se ofrece tiene que
    ser exactamente lo que `registrar_llegada` acepta, y el alta no mira eso.
    Dos criterios distintos dejarían filas que existen y no se ven, o que se
    ven y no aceptan a nadie.
    """
    salas = {c["id"]: c["name"] for c in consultorios.list()}
    resultado = []
    for bloque in blocks.espontaneos_del_dia(day):
        profesional = catalog.get_resource(bloque["resource_id"])
        resultado.append(BloqueDeLaFila(
            id=bloque["id"],
            resource_id=bloque["resource_id"],
            profesional=profesional.name if profesional else bloque["resource_id"],
            consultorio_id=bloque["consultorio_id"],
            consultorio=salas.get(bloque["consultorio_id"], bloque["consultorio_id"]),
            starts_at=bloque["starts_at"],
            ends_at=bloque["ends_at"],
            timezone=zona_del_recurso(catalog, bloque["resource_id"]),
        ))
    return resultado


@router.get("/walkins/prestaciones", response_model=list[PrestacionDeLaFila])
def prestaciones_de_la_fila(
    catalog: SqlAlchemyCatalogRepository = Depends(get_catalog_repository),
):
    """Las prestaciones que se pueden anotar: sólo las activas.

    Una dada de baja no se ofrece —igual que en el alta de un turno—, pero una
    llegada vieja que la tenga sigue en la fila con su id: el historial no se
    reescribe.
    """
    return [
        PrestacionDeLaFila(id=s.id, name=s.name)
        for s in catalog.list_services() if s.active
    ]


def _bloque_para_la_fila(
    blocks: AgendaBlockRepository, block_id: str, dia: date,
) -> dict:
    bloque = blocks.get(block_id)
    if bloque is None:
        raise HTTPException(404, "no se encontró el bloque de agenda")
    if bloque["modality"] != "espontanea":
        raise HTTPException(
            409,
            "ese bloque atiende por turnos con horario. La fila por orden de "
            "llegada es de los bloques de demanda espontánea.",
        )
    if bloque["weekday"] != dia.weekday():
        raise HTTPException(409, "ese bloque no atiende ese día de la semana")
    if dia < bloque["valid_from"] or (
        bloque["valid_to"] is not None and dia > bloque["valid_to"]
    ):
        raise HTTPException(409, "ese bloque no está vigente en esa fecha")
    return bloque


@router.post("/agenda-blocks/{block_id}/walkins", status_code=201, response_model=WalkinOut)
def registrar_llegada(
    block_id: str, data: LlegadaCreate,
    walkins: WalkinRepository = Depends(get_walkin_repository),
    blocks: AgendaBlockRepository = Depends(get_agenda_block_repository),
):
    _bloque_para_la_fila(blocks, block_id, data.day)
    try:
        return walkins.registrar(
            str(uuid4()), block_id, data.day, data.client_id, data.service_id,
        )
    except IntegrityError:
        raise HTTPException(409, "el paciente o la prestación no existen")


@router.get("/agenda-blocks/{block_id}/walkins", response_model=list[WalkinOut])
def ver_la_fila(
    block_id: str, day: date, solo_activos: bool = False,
    walkins: WalkinRepository = Depends(get_walkin_repository),
):
    return walkins.cola(block_id, day, solo_activos)


def _cambiar(walkins: WalkinRepository, walkin_id: str, nuevo: str) -> dict:
    try:
        return walkins.cambiar_estado(walkin_id, nuevo)
    except KeyError:
        raise HTTPException(404, "no se encontró la llegada")
    except TransicionInvalida:
        raise HTTPException(409, "ese cambio de estado no está permitido")


@router.post("/walkins/{walkin_id}/llamar", response_model=WalkinOut)
def llamar(
    walkin_id: str, walkins: WalkinRepository = Depends(get_walkin_repository),
):
    """El profesional lo hace pasar. Deja de estar esperando."""
    return _cambiar(walkins, walkin_id, EN_ATENCION)


@router.post("/walkins/{walkin_id}/completar", response_model=WalkinOut)
def completar(
    walkin_id: str, walkins: WalkinRepository = Depends(get_walkin_repository),
):
    return _cambiar(walkins, walkin_id, ATENDIDO)


@router.post("/walkins/{walkin_id}/cancelar", response_model=WalkinOut)
def cancelar(
    walkin_id: str, walkins: WalkinRepository = Depends(get_walkin_repository),
):
    """Se fue sin esperar, o se anotó por error.

    No borra la fila: sale de la cola de espera pero **conserva su número**. El
    orden de llegada es histórico (ver `walkins.py`).
    """
    return _cambiar(walkins, walkin_id, CANCELADO)
