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
"""
from datetime import date
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from ..dependencies import get_agenda_block_repository, get_walkin_repository
from ..services.agenda_blocks import AgendaBlockRepository
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
