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
from libracore.feriados import FueraDeCobertura, feriados_de
from libragenda.catalog_repository import SqlAlchemyCatalogRepository
from libragenda.domain import Holiday
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


class ImportacionPedida(BaseModel):
    anio: int


class ImportacionHecha(BaseModel):
    anio: int
    importados: int
    ya_estaban: int


@router.post("/importar", status_code=200, response_model=ImportacionHecha)
def importar_feriados_nacionales(
    branch_id: str, data: ImportacionPedida,
    catalog: SqlAlchemyCatalogRepository = Depends(get_catalog_repository),
):
    """Trae los feriados nacionales de un año a esta sucursal.

    El catálogo lo pone LibraCore (`libracore.feriados`), que lo empaqueta como
    archivo — no hay llamada a internet acá.

    🔑 **Es idempotente por día**, y eso no es una comodidad: es lo que hace
    que esto se pueda usar sin la baja que el catálogo de feriados de
    LibraGenda todavía no tiene (ver el docstring del módulo). Reimportar el
    mismo año no duplica nada; lo que no se puede es corregir un feriado ya
    cargado.

    🔴 **El feed propone, no dispone.** Lo que entra son filas comunes de la
    sucursal: quien administra puede sumarles los provinciales y los cierres
    propios, y la excepción puntual del recurso le sigue ganando al feriado —
    que es lo que LibraGenda ya decide.
    """
    if catalog.get_branch(branch_id) is None:
        raise HTTPException(404, "branch not found")
    try:
        del_anio = feriados_de(data.anio)
    except FueraDeCobertura as exc:
        # 422 y no una importación vacía: que el año no esté en el catálogo
        # empaquetado no es "ese año no tiene feriados", y devolver 0 se leería
        # exactamente igual que un año ya importado.
        raise HTTPException(422, str(exc))

    ya_cargados = {feriado.day for feriado in catalog.list_holidays(branch_id)}
    importados = 0
    for feriado in del_anio:
        dia = date.fromisoformat(feriado["fecha"])
        if dia in ya_cargados:
            continue
        catalog.add_holiday(Holiday(branch_id, dia, feriado["nombre"]))
        importados += 1
    return ImportacionHecha(
        anio=data.anio,
        importados=importados,
        ya_estaban=len(del_anio) - importados,
    )
