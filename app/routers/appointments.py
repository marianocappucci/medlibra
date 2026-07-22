from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from libragenda import (
    AppointmentConflict,
    AppointmentNotFound,
    AppointmentUnavailable,
    InvalidTransition,
)

from ..dependencies import get_appointment_service
from ..services.appointments import AppointmentService, ServiceNotFound

router = APIRouter()


class AppointmentRequest(BaseModel):
    resource_id: str
    service_id: str
    client_id: str
    starts_at: datetime


@router.post("/appointments", status_code=201)
def create_appointment(
    data: AppointmentRequest,
    service: AppointmentService = Depends(get_appointment_service),
):
    try:
        appointment = service.create(
            data.resource_id, data.service_id, data.client_id, data.starts_at
        )
    except ServiceNotFound:
        raise HTTPException(404, "service not found")
    except AppointmentConflict:
        raise HTTPException(409, "appointment conflict")
    except AppointmentUnavailable:
        raise HTTPException(409, "appointment unavailable")
    return {"id": appointment.id, "status": appointment.status.value, "ends_at": appointment.ends_at}


@router.post("/appointments/{appointment_id}/confirm")
def confirm_appointment(
    appointment_id: str,
    service: AppointmentService = Depends(get_appointment_service),
):
    try:
        appointment = service.confirm(appointment_id)
    except AppointmentNotFound:
        raise HTTPException(404, "appointment not found")
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc))
    return {"id": appointment.id, "status": appointment.status.value}
