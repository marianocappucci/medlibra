from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..dependencies import get_business_settings_repository
from ..services.business_settings import BusinessSettingsRepository

router = APIRouter(prefix="/business", tags=["business"])


class BusinessSettingsIn(BaseModel):
    business_name: str | None = None
    currency: str = "ARS"


class BusinessSettingsOut(BaseModel):
    business_name: str | None
    currency: str


@router.get("", response_model=BusinessSettingsOut)
def get_settings(settings: BusinessSettingsRepository = Depends(get_business_settings_repository)):
    return settings.get()


@router.put("", response_model=BusinessSettingsOut)
def update_settings(
    data: BusinessSettingsIn,
    settings: BusinessSettingsRepository = Depends(get_business_settings_repository),
):
    return settings.update(data.business_name, data.currency)
