"""Feriados por sucursal: alta y listado.

El feriado cierra **todos** los recursos de la sucursal ese día. Vive en
LibraGenda (`Holiday`, tabla `holidays`), no en este producto: la regla que
lo evalúa es del motor y la comparte MedLibra. Acá sólo se lo expone.

> 🔴 **No hay baja ni edición, y no es un olvido.** El pin `libragenda@v0.9.0`
> expone del catálogo de feriados únicamente `add_holiday()` y
> `list_holidays()` — no tiene `get`/`update`/`delete`, a diferencia de
> disponibilidad, bloqueos y excepciones, que sí siguen esa convención
> (`availability_repository.py`). Completar el repositorio de feriados es
> cambio del motor + tag + suba de pin; escribir esa baja acá sería copiar en
> el producto una pieza que pertenece al motor, y después copiarla otra vez en
> MedLibra. Mientras tanto un feriado mal cargado se corrige en base.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from libragenda.domain import Holiday
from libragenda.catalog_repository import SqlAlchemyCatalogRepository
from pydantic import BaseModel

from ..dependencies import get_catalog_repository

router = APIRouter(prefix="/branches/{branch_id}/holidays", tags=["holidays"])


class HolidayCreate(BaseModel):
    day: date
    name: str


class HolidayOut(BaseModel):
    branch_id: str
    day: date
    name: str


@router.post("", status_code=201, response_model=HolidayOut)
def create_holiday(
    branch_id: str, data: HolidayCreate,
    catalog: SqlAlchemyCatalogRepository = Depends(get_catalog_repository),
):
    if catalog.get_branch(branch_id) is None:
        raise HTTPException(404, "branch not found")
    try:
        holiday = Holiday(branch_id, data.day, data.name)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    catalog.add_holiday(holiday)
    return holiday


@router.get("", response_model=list[HolidayOut])
def list_holidays(
    branch_id: str,
    catalog: SqlAlchemyCatalogRepository = Depends(get_catalog_repository),
):
    return sorted(catalog.list_holidays(branch_id), key=lambda item: item.day)
