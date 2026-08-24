"""CRUD de consultorios: las salas donde se atiende.

Ver `app/services/consultorios.py` para por qué un consultorio no es un
`Resource` de LibraGenda.
"""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from ..dependencies import get_consultorio_repository
from ..services.consultorios import ConsultorioRepository

router = APIRouter(prefix="/consultorios", tags=["consultorios"])


class ConsultorioCreate(BaseModel):
    id: str
    name: str
    branch_id: str | None = None
    active: bool = True


class ConsultorioUpdate(BaseModel):
    name: str
    branch_id: str | None = None
    active: bool = True


class ConsultorioOut(BaseModel):
    id: str
    name: str
    branch_id: str | None
    active: bool


@router.post("", status_code=201, response_model=ConsultorioOut)
def create_consultorio(
    data: ConsultorioCreate,
    repo: ConsultorioRepository = Depends(get_consultorio_repository),
):
    if not data.id.strip() or not data.name.strip():
        raise HTTPException(422, "el consultorio necesita id y nombre")
    try:
        return repo.create(data.id, data.name, data.branch_id, data.active)
    except IntegrityError:
        raise HTTPException(409, "ya existe un consultorio con ese identificador")


@router.get("", response_model=list[ConsultorioOut])
def list_consultorios(repo: ConsultorioRepository = Depends(get_consultorio_repository)):
    return repo.list()


@router.get("/{consultorio_id}", response_model=ConsultorioOut)
def get_consultorio(
    consultorio_id: str,
    repo: ConsultorioRepository = Depends(get_consultorio_repository),
):
    item = repo.get(consultorio_id)
    if item is None:
        raise HTTPException(404, "no se encontró el consultorio")
    return item


@router.put("/{consultorio_id}", response_model=ConsultorioOut)
def update_consultorio(
    consultorio_id: str, data: ConsultorioUpdate,
    repo: ConsultorioRepository = Depends(get_consultorio_repository),
):
    if not data.name.strip():
        raise HTTPException(422, "el consultorio necesita un nombre")
    try:
        return repo.update(consultorio_id, data.name, data.branch_id, data.active)
    except KeyError:
        raise HTTPException(404, "no se encontró el consultorio")


@router.delete("/{consultorio_id}", status_code=204)
def delete_consultorio(
    consultorio_id: str,
    repo: ConsultorioRepository = Depends(get_consultorio_repository),
):
    try:
        repo.delete(consultorio_id)
    except KeyError:
        raise HTTPException(404, "no se encontró el consultorio")
    except IntegrityError:
        # Tiene bloques de agenda o turnos colgando. Borrarlo en cascada
        # borraría la agenda de alguien sin avisar; desactivarlo lo saca de las
        # listas y deja el historial en pie.
        raise HTTPException(
            409,
            "el consultorio tiene agenda o turnos asociados. Desactivalo en vez "
            "de borrarlo.",
        )
    return Response(status_code=204)
