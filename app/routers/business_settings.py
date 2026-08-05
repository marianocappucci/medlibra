from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..dependencies import get_business_settings_repository
from ..services.business_settings import BusinessSettingsRepository
from ..services.iva_rates import InvalidIvaRate

router = APIRouter(prefix="/business", tags=["business"])


class BusinessSettingsIn(BaseModel):
    business_name: str | None = None
    currency: str = "ARS"
    # Omitirla deja la que estaba: un PUT que sólo cambia el nombre del
    # consultorio no tiene por qué moverle la alicuota a la facturacion.
    default_iva_rate: Decimal | None = None


class BusinessSettingsOut(BaseModel):
    business_name: str | None
    currency: str
    default_iva_rate: Decimal


@router.get("", response_model=BusinessSettingsOut)
def get_settings(settings: BusinessSettingsRepository = Depends(get_business_settings_repository)):
    return settings.get()


@router.put("", response_model=BusinessSettingsOut)
def update_settings(
    data: BusinessSettingsIn,
    settings: BusinessSettingsRepository = Depends(get_business_settings_repository),
):
    try:
        return settings.update(data.business_name, data.currency, data.default_iva_rate)
    except InvalidIvaRate as exc:
        raise HTTPException(422, str(exc))
