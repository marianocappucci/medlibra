from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import mensajes_agenda as mensajes
from ..dependencies import get_appointment_service
from ..services.appointments import AppointmentService
from ._instantes import InstanteUTC

router = APIRouter(tags=["agenda"])


class AppointmentOut(BaseModel):
    id: str
    resource_id: str
    service_id: str
    client_id: str
    starts_at: InstanteUTC
    ends_at: InstanteUTC
    status: str
    reason: str | None = None


@router.get("/resources/{resource_id}/agenda", response_model=list[AppointmentOut])
def get_agenda(
    resource_id: str,
    date_from: date,
    date_to: date,
    service: AppointmentService = Depends(get_appointment_service),
):
    if date_to < date_from:
        raise HTTPException(422, mensajes.RANGO_INVERTIDO)
    return [
        AppointmentOut(
            id=item.id, resource_id=item.resource_id, service_id=item.service_id,
            client_id=item.client_id, starts_at=item.starts_at, ends_at=item.ends_at,
            status=item.status.value, reason=item.reason,
        )
        for item in service.agenda(resource_id, date_from, date_to)
    ]
