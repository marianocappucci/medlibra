"""Qué consultas se mandaron a Contalibra, y cuáles no pudieron.

🔴 **Existe para que un envío fallido no sea invisible.** Completar un turno no
se rompe porque Contalibra no conteste —la atención ya ocurrió—, pero sin esta
pantalla el resultado sería una consulta que no se facturó y de la que nadie se
entera. Es la peor de las dos mitades: la plata se pierde en silencio.

El reintento es seguro: Contalibra es idempotente por `(sistema, referencia)`,
así que mandar de nuevo una consulta que sí había llegado devuelve la misma
venta y la misma factura, no una segunda.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ._instantes import InstanteUTC
from ..dependencies import (
    get_appointment_service,
    get_catalog_repository,
    get_business_settings_repository,
    get_envio_contalibra_repository,
    get_iva_rate_repository,
    get_patient_repository,
    get_resource_price_repository,
    get_service_price_repository,
)
from ..services import contalibra
from ..services.appointments import AppointmentService
from ..services.business_settings import BusinessSettingsRepository
from ..services.iva_rates import IvaRateRepository
from ..services.patients import PatientRepository
from ..services.resource_prices import ResourcePriceRepository, precio_del_turno
from ..services.service_prices import ServicePriceRepository

router = APIRouter(prefix="/facturacion-externa", tags=["facturacion-externa"])


class EnvioOut(BaseModel):
    appointment_id: str
    estado: str
    venta_id: int | None
    error: str
    intentos: int
    actualizado: InstanteUTC


class EstadoOut(BaseModel):
    #: `""` cuando esta instancia no manda a Contalibra y factura por su cuenta.
    destino: str
    envios: list[EnvioOut]


@router.get("", response_model=EstadoOut)
def listar(
    solo_pendientes: bool = False,
    envios: contalibra.EnvioRepository = Depends(get_envio_contalibra_repository),
):
    """Los envíos, con el destino al lado.

    El destino va en la respuesta y no se asume: una lista vacía significa cosas
    opuestas según esté configurado o no —"todo salió bien" contra "esto ni
    siquiera está prendido"— y sin el dato la pantalla no las puede distinguir.
    """
    return {"destino": contalibra.destino(), "envios": envios.listar(solo_pendientes)}


@router.post("/{appointment_id}/reintentar", response_model=EnvioOut)
async def reintentar(
    appointment_id: str,
    envios: contalibra.EnvioRepository = Depends(get_envio_contalibra_repository),
    service: AppointmentService = Depends(get_appointment_service),
    patients: PatientRepository = Depends(get_patient_repository),
    service_prices: ServicePriceRepository = Depends(get_service_price_repository),
    resource_prices: ResourcePriceRepository = Depends(get_resource_price_repository),
    catalog=Depends(get_catalog_repository),
    iva_rates: IvaRateRepository = Depends(get_iva_rate_repository),
    business: BusinessSettingsRepository = Depends(get_business_settings_repository),
):
    """Vuelve a mandar una consulta que no llegó.

    **Se recalcula todo desde el turno**, no se guarda el cuerpo del envío
    fallido: si entre el intento y el reintento cambió el honorario, lo que
    tiene que viajar es el precio de hoy, no el que se congeló en un JSON.
    """
    if not contalibra.destino():
        raise HTTPException(
            409,
            "Esta instancia no manda las consultas a Contalibra "
            "(falta `CONTALIBRA_URL`). No hay nada que reintentar.",
        )
    turno = service.appointments.get(appointment_id)
    if turno is None:
        raise HTTPException(404, "No se encontró el turno.")

    recurso = catalog.get_resource(turno.resource_id)
    precio = precio_del_turno(
        resource_prices, service_prices,
        turno.service_id, turno.resource_id,
        recurso.branch_id if recurso else None,
    )
    if precio is None:
        raise HTTPException(
            422,
            "Ese turno no tiene precio configurado, así que no hay nada que "
            "facturar. Cargá el honorario del profesional o el precio de la sede.",
        )

    paciente = patients.get(turno.client_id) or {}
    try:
        respuesta = await contalibra.enviar_consulta(
            appointment_id=appointment_id,
            fecha=_dia(turno.starts_at),
            descripcion=turno.service_id,
            importe=precio["price"],
            medio_pago="efectivo",
            paciente=paciente,
            iva_rate=iva_rates.resolve(
                turno.service_id, business.get()["default_iva_rate"],
            ),
        )
    except Exception as exc:  # noqa: BLE001 — el fallo se registra, no se propaga
        return envios.registrar(appointment_id, contalibra.ERROR, error=str(exc))
    venta = (respuesta or {}).get("venta") or {}
    return envios.registrar(
        appointment_id, contalibra.ENVIADO, venta_id=venta.get("id"),
    )


def _dia(instante: datetime) -> str:
    return instante.date().isoformat()
