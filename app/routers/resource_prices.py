"""Honorarios: cuánto sale cada prestación con cada profesional.

Pisa al precio por sede cuando existe. Ver `app/services/resource_prices.py`
para el orden de resolución y por qué hay un solo resolvedor.

El prefijo es `/resources/{id}/prices` y no `/services/{id}/resource-prices`
porque es como se carga: se entra a la ficha del profesional y se le ponen sus
honorarios, uno por prestación. La otra forma obligaría a recorrer las
prestaciones una por una para configurar a una sola persona.
"""
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from ..dependencies import get_resource_price_repository
from ..services.resource_prices import ResourcePriceRepository

router = APIRouter(prefix="/resources/{resource_id}/prices", tags=["honorarios"])


class HonorarioSet(BaseModel):
    service_id: str
    price: Decimal


class HonorarioOut(BaseModel):
    id: str
    service_id: str
    resource_id: str
    price: Decimal


@router.put("", response_model=HonorarioOut)
def set_honorario(
    resource_id: str, data: HonorarioSet,
    prices: ResourcePriceRepository = Depends(get_resource_price_repository),
):
    """Crea o actualiza el honorario de (prestación, profesional)."""
    if data.price < 0:
        raise HTTPException(422, "el honorario no puede ser negativo")
    try:
        return prices.set_price(str(uuid4()), data.service_id, resource_id, data.price)
    except IntegrityError:
        raise HTTPException(409, "el profesional o la prestación no existen")


@router.get("", response_model=list[HonorarioOut])
def list_honorarios(
    resource_id: str,
    prices: ResourcePriceRepository = Depends(get_resource_price_repository),
):
    return prices.list_for_resource(resource_id)


@router.delete("/{service_id}", status_code=204)
def delete_honorario(
    resource_id: str, service_id: str,
    prices: ResourcePriceRepository = Depends(get_resource_price_repository),
):
    """Saca el honorario propio. La prestación vuelve a cobrarse al precio de
    la sede — no queda sin precio."""
    try:
        prices.delete(service_id, resource_id)
    except KeyError:
        raise HTTPException(404, "ese profesional no tiene honorario para esa prestación")
    return Response(status_code=204)
