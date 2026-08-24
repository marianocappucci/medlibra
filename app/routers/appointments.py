import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from libragenda import (
    AppointmentConflict,
    AppointmentNotFound,
    AppointmentUnavailable,
    DepositStatus,
    InvalidTransition,
)
from libragenda.catalog_repository import SqlAlchemyCatalogRepository
from libragenda.repositories import DepositRepository

from .. import mensajes_agenda as mensajes
from ..dependencies import (
    get_appointment_service,
    get_business_settings_repository,
    get_catalog_repository,
    get_deposit_repository,
    get_envio_contalibra_repository,
    get_iva_rate_repository,
    get_patient_repository,
    get_resource_price_repository,
    get_service_price_repository,
)
from ..modules_gate import get_module_repository
from ..services.appointments import (
    AppointmentService,
    ConsultorioOcupado,
    OutsideBusinessHours,
    ServiceNotFound,
)
from ..services import contalibra
from ..services.business_settings import BusinessSettingsRepository
from ..services.iva_rates import IvaRateRepository
from ..services.modules import ModuleRepository
from ..services.patients import PatientRepository
from ..services.resource_prices import ResourcePriceRepository, precio_del_turno
from ..services.service_prices import ServicePriceRepository

logger = logging.getLogger(__name__)

router = APIRouter()


class AppointmentRequest(BaseModel):
    resource_id: str
    service_id: str
    client_id: str
    starts_at: datetime


class CancelRequest(BaseModel):
    reason: str | None = None


class CompleteRequest(BaseModel):
    medio_pago: str | None = None


class RescheduleRequest(BaseModel):
    starts_at: datetime
    reason: str | None = None


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
        raise HTTPException(404, mensajes.SERVICIO_NO_ENCONTRADO)
    except OutsideBusinessHours:
        raise HTTPException(409, mensajes.FUERA_DE_HORARIO)
    except ConsultorioOcupado as exc:
        raise HTTPException(*mensajes.describir(exc))
    except AppointmentConflict:
        raise HTTPException(*mensajes.describir(AppointmentConflict("")))
    except AppointmentUnavailable:
        raise HTTPException(*mensajes.describir(AppointmentUnavailable("")))
    return {"id": appointment.id, "status": appointment.status.value, "ends_at": appointment.ends_at}


@router.post("/appointments/{appointment_id}/confirm")
def confirm_appointment(
    appointment_id: str,
    service: AppointmentService = Depends(get_appointment_service),
):
    try:
        appointment = service.confirm(appointment_id)
    except AppointmentNotFound:
        raise HTTPException(*mensajes.describir(AppointmentNotFound("")))
    except InvalidTransition as exc:
        raise HTTPException(*mensajes.describir(exc))
    return {"id": appointment.id, "status": appointment.status.value}


@router.post("/appointments/{appointment_id}/cancel")
def cancel_appointment(
    appointment_id: str,
    data: CancelRequest = CancelRequest(),
    service: AppointmentService = Depends(get_appointment_service),
):
    try:
        appointment = service.cancel(appointment_id, reason=data.reason)
    except AppointmentNotFound:
        raise HTTPException(*mensajes.describir(AppointmentNotFound("")))
    except InvalidTransition as exc:
        raise HTTPException(*mensajes.describir(exc))
    return {"id": appointment.id, "status": appointment.status.value, "reason": appointment.reason}


@router.post("/appointments/{appointment_id}/reschedule")
def reschedule_appointment(
    appointment_id: str,
    data: RescheduleRequest,
    service: AppointmentService = Depends(get_appointment_service),
):
    try:
        appointment = service.reschedule(appointment_id, data.starts_at, reason=data.reason)
    except AppointmentNotFound:
        raise HTTPException(*mensajes.describir(AppointmentNotFound("")))
    except InvalidTransition as exc:
        raise HTTPException(*mensajes.describir(exc))
    except OutsideBusinessHours:
        raise HTTPException(409, mensajes.FUERA_DE_HORARIO)
    except ConsultorioOcupado as exc:
        raise HTTPException(*mensajes.describir(exc))
    except AppointmentConflict:
        raise HTTPException(*mensajes.describir(AppointmentConflict("")))
    except AppointmentUnavailable:
        raise HTTPException(*mensajes.describir(AppointmentUnavailable("")))
    return {
        "id": appointment.id, "status": appointment.status.value,
        "starts_at": appointment.starts_at, "reason": appointment.reason,
    }


@router.post("/appointments/{appointment_id}/complete")
async def complete_appointment(
    appointment_id: str,
    data: CompleteRequest = CompleteRequest(),
    service: AppointmentService = Depends(get_appointment_service),
    patients: PatientRepository = Depends(get_patient_repository),
    service_prices: ServicePriceRepository = Depends(get_service_price_repository),
    resource_prices: ResourcePriceRepository = Depends(get_resource_price_repository),
    deposits: DepositRepository = Depends(get_deposit_repository),
    catalog: SqlAlchemyCatalogRepository = Depends(get_catalog_repository),
    modules: ModuleRepository = Depends(get_module_repository),
    iva_rates: IvaRateRepository = Depends(get_iva_rate_repository),
    business: BusinessSettingsRepository = Depends(get_business_settings_repository),
    envios: contalibra.EnvioRepository = Depends(get_envio_contalibra_repository),
):
    """Completa el turno y, si hay precio configurado Y el plan incluye el
    módulo "facturacion" (ver plans.py), manda la consulta a Contalibra.

    🔴 **Este producto ya no factura** (ADR-036): no queda ningún camino de
    emisión local, así que no hay forma de que salgan dos comprobantes por una
    consulta. Sin precio configurado, o sin el módulo habilitado, no se manda
    nada — completar el turno nunca se bloquea por el plan.

    ⚠️ **Sin `CONTALIBRA_URL` la consulta queda registrada como NO facturada**
    (`estado="sin_destino"`), visible en `GET /facturacion-externa`. El turno se
    completa igual: la atención ya ocurrió, y `COMPLETED` no admite otra
    transición, así que un turno que no se puede completar queda trabado para
    siempre.

    La validacion del medio de pago (requerido si hay saldo) corre ANTES de
    completar el turno -- si faltara, el turno quedaría completado, sin cobrar y
    sin forma de reintentar."""
    current = service.appointments.get(appointment_id)
    if current is None:
        raise HTTPException(*mensajes.describir(AppointmentNotFound("")))

    price_row = None
    patient: dict = {}
    deposit = None
    if modules.is_enabled("facturacion"):
        resource = catalog.get_resource(current.resource_id)
        branch_id = resource.branch_id if resource else None
        # 🔴 UN SOLO resolvedor. Lo que se cobra es el honorario del profesional
        # si lo tiene, y si no el precio de lista de la sede (ver
        # `app/services/resource_prices.py`). Copiar acá un
        # `service_prices.get(...)` —o hacerlo en la seña, o en el envío a
        # facturar— deja el honorario aplicando en un camino y no en el otro, y
        # la diferencia aparece como un descuadre que nadie sabe de dónde sale.
        price_row = precio_del_turno(
            resource_prices, service_prices,
            current.service_id, current.resource_id, branch_id,
        )
    if price_row is not None:
        patient = patients.get(current.client_id) or {}
        deposit = deposits.get_by_appointment(appointment_id)
        paid = deposit is not None and deposit.status is DepositStatus.PAID
        balance = price_row["price"] - (deposit.amount if paid else 0)
        if balance > 0 and not data.medio_pago:
            raise HTTPException(422, f"medio_pago requerido para saldo de {balance}")

    try:
        appointment = service.complete(appointment_id)
    except AppointmentNotFound:
        raise HTTPException(*mensajes.describir(AppointmentNotFound("")))
    except InvalidTransition as exc:
        raise HTTPException(*mensajes.describir(exc))

    enviado_a_contalibra = None
    if price_row is not None:
        # 🔴 **Este producto ya no factura.** La facturación vive en Contalibra
        # desde ADR-036: acá no queda ningún camino de emisión local, así que no
        # hay forma de que salgan dos comprobantes por una consulta.
        if contalibra.destino():
            enviado_a_contalibra = await _mandar(
                envios, appointment_id, current, patient,
                price_row["price"], data.medio_pago or "efectivo",
                # La alícuota de ESTA prestación (ADR-027). Viaja con la
                # consulta: en salud el caso normal es el exento, y sin mandarla
                # Contalibra usaría su default del 21%.
                iva_rate=iva_rates.resolve(
                    current.service_id, business.get()["default_iva_rate"],
                ),
            )
        else:
            # 🔴 **Sin destino, la consulta queda registrada como NO facturada.**
            # El turno se completa igual —la atención ocurrió— pero una consulta
            # con precio que no se facturó y de la que nadie se entera es plata
            # que se pierde en silencio. Queda en `/facturacion-externa` con
            # `estado="sin_destino"`, y se manda configurando `CONTALIBRA_URL` y
            # reintentando **a mano** — no hay reintento automático de nada.
            enviado_a_contalibra = envios.registrar(
                appointment_id, contalibra.SIN_DESTINO,
                error="CONTALIBRA_URL no está configurada: la consulta no se facturó.",
            )

    return {
        "id": appointment.id, "status": appointment.status.value,
        "contalibra": enviado_a_contalibra,
    }


async def _mandar(
    envios: contalibra.EnvioRepository, appointment_id: str, turno,
    patient: dict, importe, medio_pago: str, iva_rate=None,
) -> dict:
    """Manda la consulta a Contalibra y **deja registro pase lo que pase**.

    🔴 **Un fallo acá no rompe el completar del turno.** La atención ya ocurrió;
    negarse a completarla porque la contabilidad de otro producto no contesta
    sería castigar al consultorio por una falla que no es suya. Pero tampoco
    puede terminar en una consulta que no se facturó y de la que nadie se
    entera: por eso el error queda en `envios_a_contalibra`, se lista en
    `GET /facturacion-externa` y se puede reintentar.
    """
    try:
        respuesta = await contalibra.enviar_consulta(
            appointment_id=appointment_id,
            fecha=turno.starts_at.date().isoformat(),
            descripcion=turno.service_id,
            importe=importe,
            medio_pago=medio_pago,
            paciente=patient,
            iva_rate=iva_rate,
        )
    except Exception as exc:  # noqa: BLE001 — cualquier fallo se registra igual
        logger.exception("No se pudo mandar la consulta %s a Contalibra", appointment_id)
        return envios.registrar(appointment_id, contalibra.ERROR, error=str(exc))
    venta = (respuesta or {}).get("venta") or {}
    return envios.registrar(
        appointment_id, contalibra.ENVIADO, venta_id=venta.get("id"),
    )
