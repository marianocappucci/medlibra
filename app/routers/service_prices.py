from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from ..dependencies import get_service_price_repository
from ..services.service_prices import ServicePriceRepository

router = APIRouter(prefix="/services/{service_id}/prices", tags=["service-prices"])


class PriceSet(BaseModel):
    branch_id: str
    price: Decimal


class PriceOut(BaseModel):
    id: str
    service_id: str
    branch_id: str
    price: Decimal


@router.put("", response_model=PriceOut)
def set_price(
    service_id: str, data: PriceSet,
    prices: ServicePriceRepository = Depends(get_service_price_repository),
):
    """Create or update the price for (service_id, data.branch_id)."""
    return prices.set_price(str(uuid4()), service_id, data.branch_id, data.price)


@router.get("", response_model=list[PriceOut])
def list_prices(
    service_id: str, prices: ServicePriceRepository = Depends(get_service_price_repository),
):
    return prices.list_for_service(service_id)


@router.delete("/{branch_id}", status_code=204)
def delete_price(
    service_id: str, branch_id: str,
    prices: ServicePriceRepository = Depends(get_service_price_repository),
):
    try:
        prices.delete(service_id, branch_id)
    except KeyError:
        raise HTTPException(404, "price not found")
    return Response(status_code=204)
