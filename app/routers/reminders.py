from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from libragenda import ReminderDispatcher

from ..dependencies import get_reminder_dispatcher
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
def dispatch_reminders(dispatcher: ReminderDispatcher = Depends(get_reminder_dispatcher)):
    """Envia todos los recordatorios vencidos y aun no enviados.

    Pensado para un cron/scheduler externo -- este repo no corre uno.
    """
    return dispatcher.dispatch(datetime.now(timezone.utc))
