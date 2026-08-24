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
from ..services.billing import invoice_appointment
from ..services.business_settings import BusinessSettingsRepository
from ..services.iva_rates import IvaRateRepository
from ..services.modules import ModuleRepository
from ..services.patients import PatientRepository
from ..services.resource_prices import ResourcePriceRepository, precio_del_turno
from ..services.service_prices import ServicePriceRepository

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
):
    """Completa el turno y, si hay un precio configurado para el servicio
    en la sucursal Y el plan incluye el módulo "facturacion" (ver
    plans.py), factura el total con LibraCore (una sola factura,
    reconciliando la sena ya cobrada -- si existe -- y el saldo restante
    como movimientos de caja separados). Sin precio configurado, o sin el
    módulo habilitado, no factura nada -- completar el turno nunca se
    bloquea por el plan, solo se salta la parte de facturación.

    La validacion de facturacion (medio_pago requerido si hay saldo) corre
    ANTES de completar el turno en LibraGenda -- si faltara, el turno no
    queda completado sin factura y sin forma de reintentar (COMPLETED no
    admite otra transicion)."""
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

    factura = None
    if price_row is not None:
        paid = deposit is not None and deposit.status is DepositStatus.PAID
        factura = await invoice_appointment(
            patient, price_row["price"], appointment_id,
            deposit_amount=deposit.amount if paid else None,
            deposit_medio_pago=deposit.medio_pago if paid else None,
            balance_medio_pago=data.medio_pago,
            iva_rate=iva_rates.resolve(
                current.service_id, business.get()["default_iva_rate"],
            ),
        )

    return {"id": appointment.id, "status": appointment.status.value, "factura": factura}
