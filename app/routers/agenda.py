"""La agenda de turnos: lo que la pantalla lee para dibujarla.

🔴 **El catálogo que la Agenda necesita también vive acá, y no en los routers de
configuración.** `/resources`, `/branches` y `/services` son `admin_only`, y la
Agenda los pedía en un solo `Promise.all`: para el mostrador —staff, que es
quien atiende el teléfono— el primer 403 tumbaba la carga entera. La pantalla
decía *"No hay profesionales activos. Cargá uno en Configuración."* y no dejaba
dar un turno. Abrir esos routers a `staff` le daría además el alta, la edición y
el borrado del catálogo. En vez de eso, este router (que ya es `staff_or_admin`)
sirve una lectura recortada a lo que la Agenda usa — el mismo criterio que
`walkins.py` (ADR-038). Ver ADR-039.
"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from libragenda.catalog_repository import SqlAlchemyCatalogRepository
from pydantic import BaseModel

from .. import mensajes_agenda as mensajes
from ..dependencies import get_appointment_service, get_branch_repository, get_catalog_repository
from ..services.appointments import AppointmentService
from ..services.branches import BranchRepository
from ._instantes import InstanteUTC

router = APIRouter(tags=["agenda"])


class ProfesionalDeLaAgenda(BaseModel):
    id: str
    name: str
    branch_id: str | None
    active: bool


class SedeDeLaAgenda(BaseModel):
    """Sin teléfono ni dirección: la Agenda sólo necesita el nombre y **el
    huso**, que es con el que dice a qué día y a qué hora cae cada turno
    (ADR-028)."""

    id: str
    name: str
    timezone: str


class PrestacionDeLaAgenda(BaseModel):
    id: str
    name: str
    duration_minutes: int
    active: bool


class CatalogoDeLaAgenda(BaseModel):
    profesionales: list[ProfesionalDeLaAgenda]
    sedes: list[SedeDeLaAgenda]
    prestaciones: list[PrestacionDeLaAgenda]


@router.get("/agenda/catalogo", response_model=CatalogoDeLaAgenda)
def catalogo_de_la_agenda(
    catalog: SqlAlchemyCatalogRepository = Depends(get_catalog_repository),
    branches: BranchRepository = Depends(get_branch_repository),
):
    """Profesionales, sedes y prestaciones, **también los dados de baja**.

    No se filtra acá, a propósito: la pantalla filtra los activos para ofrecer
    y para dibujar carriles, pero un turno viejo con una prestación dada de baja
    tiene que seguir mostrando su nombre y no el id.
    """
    return CatalogoDeLaAgenda(
        profesionales=[
            ProfesionalDeLaAgenda(
                id=r.id, name=r.name, branch_id=r.branch_id, active=r.active,
            )
            for r in catalog.list_resources()
        ],
        sedes=[
            SedeDeLaAgenda(id=b["id"], name=b["name"], timezone=b["timezone"])
            for b in branches.list()
        ],
        prestaciones=[
            PrestacionDeLaAgenda(
                id=s.id, name=s.name,
                duration_minutes=int(s.duration.total_seconds() // 60),
                active=s.active,
            )
            for s in catalog.list_services()
        ],
    )


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
