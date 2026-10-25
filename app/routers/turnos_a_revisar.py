"""Los turnos que se atendieron sin conexión y en la web cambiaron mientras tanto: la lista «a revisar» (ADR-045).

Decisión del humano (2026-10-25): un turno atendido en la PC del consultorio que en la web se canceló o se movió **cuenta
igual** —la atención y lo cobrado valen— y **queda a revisar** para que alguien lo acomode. LibraGenda (ADR-019) anota la
atención con su motivo y expone `turnos_a_revisar` / `marcar_revisada`; la ruta que los saca por la API es del producto.

- `GET /turnos-a-revisar`: las atenciones que esperan, **en las dos puntas** (la tabla de LibraGenda baja al nodo como cualquier
  otra del espejo). Los nombres de cada fila son los de `AtencionAplicada` —lo que espera `libra-ui/TurnosARevisar`, ADR-095—,
  con el paciente, la prestación y la hora del turno para que la pantalla diga de quién es.
- `POST /turnos-a-revisar/revisadas`: «ya lo revisé». **Sólo en el central**: en el nodo la tabla es del espejo y la guarda
  la rechaza (409 `solo_en_el_central`). No cambia el turno ni la atención: acomodar el turno se hace en la agenda, a mano.
"""
from fastapi import APIRouter, Depends, HTTPException
from libragenda.atencion_en_nodo import AtencionNotFound
from pydantic import BaseModel

from .. import offline
from ..auth import get_current_user
from ..services import atencion_nodo
from ._instantes import InstanteUTC

router = APIRouter(tags=["turnos-a-revisar"])


class AtencionARevisarOut(BaseModel):
    atencion_id: str
    appointment_id: str
    estado: str
    at: InstanteUTC
    actor: str | None
    motivo: str | None
    estado_despues: str | None
    resultado: str
    revisada_at: InstanteUTC | None
    #: Para que la pantalla diga de quién es el turno sin pedir la agenda entera. `None` si el turno ya no existe.
    paciente: str | None
    servicio: str | None
    starts_at: InstanteUTC | None
    #: El huso de la sede del profesional: la hora del turno se muestra en la de la sede (ADR-028).
    zona: str | None


class RevisadasRequest(BaseModel):
    #: Los `atencion_id` de las atenciones del turno (la pantalla entrega el turno entero: una fila por atención).
    atenciones: list[str]


@router.get("/turnos-a-revisar", response_model=list[AtencionARevisarOut])
def listar_turnos_a_revisar():
    return atencion_nodo.turnos_a_revisar()


@router.post("/turnos-a-revisar/revisadas", dependencies=[Depends(offline.solo_en_el_central)])
def marcar_revisadas(data: RevisadasRequest, user: dict = Depends(get_current_user)):
    try:
        marcadas = atencion_nodo.marcar_revisadas(data.atenciones, user.get("username"))
    except AtencionNotFound:
        raise HTTPException(404, "No se encontró la atención.")
    return {"revisadas": marcadas}

