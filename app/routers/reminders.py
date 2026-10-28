from datetime import UTC, datetime, timezone

from fastapi import APIRouter, Depends
from libragenda import ReminderDispatcher
from pydantic import BaseModel

from ..avisos import enviar_recordatorios
from ..dependencies import get_proveedores_de_avisos, get_reminder_dispatcher
from ._instantes import InstanteUTC

router = APIRouter(prefix="/reminders", tags=["reminders"])


class ReminderOut(BaseModel):
    appointment_id: str
    policy_id: str
    resource_id: str
    service_id: str
    client_id: str
    starts_at: InstanteUTC


@router.post("/dispatch", response_model=list[ReminderOut])
def dispatch_reminders(
    dispatcher: ReminderDispatcher = Depends(get_reminder_dispatcher),
    proveedores=Depends(get_proveedores_de_avisos),
):
    """Envia todos los recordatorios vencidos y aun no enviados, por WhatsApp y por mail (ADR-049), y despues reintenta los
    avisos que fallaron en las ultimas 24 horas.

    Pensado para un cron/scheduler externo -- la app no corre uno; `scripts/enviar_recordatorios.py` es lo que tiene que correr
    ese cron (esta ruta pide la sesion de un admin). Es `def` y no `async def` a proposito: enviar espera a Evolution o al SMTP.
    """
    return enviar_recordatorios(dispatcher, proveedores, datetime.now(UTC))
