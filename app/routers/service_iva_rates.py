"""Alicuota de IVA por servicio. Anidado bajo `/services/{id}`, mismo
patron que `service_prices`.
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from ..dependencies import get_business_settings_repository, get_iva_rate_repository
from ..services.business_settings import BusinessSettingsRepository
from ..services.iva_rates import InvalidIvaRate, IvaRateRepository

router = APIRouter(prefix="/services/{service_id}/iva", tags=["service-iva"])


class IvaRateSet(BaseModel):
    rate: Decimal


class IvaRateOut(BaseModel):
    service_id: str
    rate: Decimal
    # `True` cuando la alicuota no es propia del servicio sino la default
    # de la instancia. Sin esto, la pantalla no puede distinguir "exento
    # porque alguien lo decidio" de "exento porque lo es todo el consultorio".
    inherited: bool


@router.put("", response_model=IvaRateOut)
def set_rate(
    service_id: str, data: IvaRateSet,
    rates: IvaRateRepository = Depends(get_iva_rate_repository),
):
    try:
        row = rates.set_rate(service_id, data.rate)
    except InvalidIvaRate as exc:
        raise HTTPException(422, str(exc))
    return IvaRateOut(service_id=service_id, rate=row["rate"], inherited=False)


@router.get("", response_model=IvaRateOut)
def get_rate(
    service_id: str,
    rates: IvaRateRepository = Depends(get_iva_rate_repository),
    settings: BusinessSettingsRepository = Depends(get_business_settings_repository),
):
    row = rates.get(service_id)
    if row is not None:
        return IvaRateOut(service_id=service_id, rate=row["rate"], inherited=False)
    return IvaRateOut(
        service_id=service_id, rate=settings.get()["default_iva_rate"], inherited=True,
    )


@router.delete("", status_code=204)
def clear_rate(
    service_id: str, rates: IvaRateRepository = Depends(get_iva_rate_repository),
):
    """Saca la alicuota propia: el servicio vuelve a heredar la de la
    instancia."""
    try:
        rates.delete(service_id)
    except KeyError:
        raise HTTPException(404, "service has no own iva rate")
    return Response(status_code=204)
