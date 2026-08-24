"""CRUD de bloques de agenda: cómo se arma la agenda de un profesional.

Un bloque es *"la Dra. Vidal atiende los lunes de 9 a 13 en el Consultorio 2,
turnos de 20 minutos, hasta el 31 de diciembre"*. Ver
`app/services/agenda_blocks.py` para qué agrega sobre la `Availability` del
motor y por qué las ventanas se derivan en vez de guardarse.

⚠️ Las horas son **hora de pared de la sede**, igual que la disponibilidad
semanal y el horario de atención (ADR-028).
"""
from datetime import date, time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from ..dependencies import get_agenda_block_repository
from ..services.agenda_blocks import DURACIONES, MODALIDADES, AgendaBlockRepository

router = APIRouter(prefix="/agenda-blocks", tags=["agenda-blocks"])


class BlockCreate(BaseModel):
    resource_id: str
    consultorio_id: str
    #: 0 = lunes … 6 = domingo. Uno por bloque: "lunes a viernes" son cinco
    #: bloques, que es lo que permite que el miércoles esté en otra sala.
    weekday: int
    starts_at: time
    ends_at: time
    valid_from: date
    #: `null` = se repite indefinidamente.
    valid_to: date | None = None
    slot_minutes: int
    modality: str = "turnos"


class BlockOut(BaseModel):
    id: str
    resource_id: str
    consultorio_id: str
    weekday: int
    starts_at: time
    ends_at: time
    valid_from: date
    valid_to: date | None
    slot_minutes: int
    modality: str


def _campos(data: BlockCreate) -> dict:
    return {
        "resource_id": data.resource_id, "consultorio_id": data.consultorio_id,
        "weekday": data.weekday, "starts_at": data.starts_at, "ends_at": data.ends_at,
        "valid_from": data.valid_from, "valid_to": data.valid_to,
        "slot_minutes": data.slot_minutes, "modality": data.modality,
    }


@router.get("/opciones")
def opciones():
    """Lo que la pantalla ofrece elegir.

    Sale del backend y no de una constante repetida en el frontend: la lista de
    duraciones es la que el repositorio valida, y dos copias divergen — la
    pantalla ofrecería un valor que el alta rechaza con 422.
    """
    return {"duraciones": list(DURACIONES), "modalidades": list(MODALIDADES)}


@router.post("", status_code=201, response_model=BlockOut)
def create_block(
    data: BlockCreate,
    repo: AgendaBlockRepository = Depends(get_agenda_block_repository),
):
    try:
        return repo.create(str(uuid4()), **_campos(data))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except IntegrityError:
        raise HTTPException(409, "el profesional o el consultorio no existen")


@router.get("", response_model=list[BlockOut])
def list_blocks(
    resource_id: str | None = None,
    repo: AgendaBlockRepository = Depends(get_agenda_block_repository),
):
    return repo.list(resource_id)


@router.put("/{block_id}", response_model=BlockOut)
def update_block(
    block_id: str, data: BlockCreate,
    repo: AgendaBlockRepository = Depends(get_agenda_block_repository),
):
    try:
        return repo.update(block_id, **_campos(data))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except KeyError:
        raise HTTPException(404, "no se encontró el bloque de agenda")


@router.delete("/{block_id}", status_code=204)
def delete_block(
    block_id: str,
    repo: AgendaBlockRepository = Depends(get_agenda_block_repository),
):
    try:
        repo.delete(block_id)
    except KeyError:
        raise HTTPException(404, "no se encontró el bloque de agenda")
    return Response(status_code=204)
