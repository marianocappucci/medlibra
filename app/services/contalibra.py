"""Mandar la consulta a Contalibra, que es donde vive la contabilidad.

Pedido del humano (2026-08-22): *"permitir enviar a facturar consultas con
enlace a contalibra"*. La pantalla de Facturación ya salió de MedLibra
(ADR-034); esto es la otra mitad.

## 🔴 Éste es el único camino. MedLibra ya no factura.

Hasta el 2026-08-24 esto era **un interruptor**: con `CONTALIBRA_URL` configurada
se mandaba, y sin ella `complete_appointment` emitía la factura acá mismo con
LibraCore/ARCA (ADR-016). El interruptor existía para que no salieran **dos
comprobantes por una consulta** — un CAE emitido no se borra, se anula con una
nota de crédito.

Con ADR-036 se fue el otro lado del interruptor: no hay motor local que emita, y
`/config/arca` no existe más. Lo que quedó en su lugar **no es silencio**: una
instancia sin `CONTALIBRA_URL` completa el turno igual —la atención ocurrió— y la
consulta queda registrada como `SIN_DESTINO`, visible en `/facturacion-externa`
junto a los envíos que fallaron. Facturarla es después configurar el destino y
reintentar, no descubrir a fin de mes que faltaba.

## Lo que se manda nunca se pierde de vista

Contalibra puede estar caída, el token puede estar mal, la red puede cortarse.
Nada de eso puede impedir **completar el turno** —la atención ya ocurrió— pero
tampoco puede terminar en una consulta que no se facturó y de la que nadie se
entera: es la peor de las dos mitades.

Cada envío deja su fila en `envios_a_contalibra`, con su estado y el error si lo
hubo. `GET /facturacion-externa` los lista y `POST
/facturacion-externa/{id}/reintentar` los reintenta. La idempotencia la garantiza
Contalibra por `(sistema, referencia)`, así que reintentar es seguro incluso si
el envío anterior llegó y la respuesta se perdió.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal

import httpx
from sqlalchemy import DateTime, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

# 🔴 El nombre del header sale de libraauth y no se escribe a mano. Es el mismo
# motor que valida del otro lado (`token_de_servicio_valido`), así que si el
# nombre cambiara alguna vez, escribirlo acá dejaría los envíos rebotando con
# 401 y el mensaje diría "no autorizado", no "el header se llama distinto".
from libraauth.session_auth import SERVICE_TOKEN_HEADER
from libragenda.sqlalchemy_repository import Base

#: Cómo se identifica este producto ante Contalibra. Junto con el id del turno
#: forma la clave de idempotencia del otro lado.
SISTEMA = "medlibra"

PENDIENTE = "pendiente"
ENVIADO = "enviado"
ERROR = "error"
#: La consulta tenia precio pero la instancia no tiene , asi
#: que no se facturo en ningun lado. No es un fallo del otro lado: es que no
#: hay otro lado configurado. Se distingue de  porque el arreglo es
#: distinto -- configurar, no reintentar contra algo que fallo.
SIN_DESTINO = "sin_destino"

#: Cuánto se espera a Contalibra. Corto a propósito: del otro lado hay un
#: pedido de CAE a ARCA, pero **este** proceso está completando un turno con
#: alguien esperando en el mostrador. Si tarda más, se registra como pendiente y
#: se reintenta — que es exactamente para lo que existe la tabla.
TIMEOUT_SEGUNDOS = 8.0


class EnvioAContalibraRow(Base):
    __tablename__ = "envios_a_contalibra"

    appointment_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    estado: Mapped[str] = mapped_column(String(20), default=PENDIENTE)
    #: El id de la venta del otro lado, cuando llegó.
    venta_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Lo que dijo Contalibra si falló. Vacío cuando salió bien.
    error: Mapped[str] = mapped_column(String(500), default="")
    intentos: Mapped[int] = mapped_column(Integer, default=0)
    actualizado: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def _to_dict(row: EnvioAContalibraRow) -> dict:
    return {
        "appointment_id": row.appointment_id, "estado": row.estado,
        "venta_id": row.venta_id, "error": row.error,
        "intentos": row.intentos, "actualizado": row.actualizado,
    }


def destino() -> str:
    """La URL de Contalibra, o `""` si esta instancia no la tiene configurada.

    🔴 **Es el interruptor de todo el módulo.** Vacía = MedLibra factura como
    siempre; con valor = MedLibra manda y NO factura.
    """
    return os.environ.get("CONTALIBRA_URL", "").strip().rstrip("/")


def _token() -> str:
    """El token de servicio con el que Contalibra nos deja entrar.

    Variable **propia** y no la `LIBRA_SERVICE_TOKEN` que este producto ya lee
    para su propio guard de entrada: son dos permisos distintos —el que nos
    dejan usar a nosotros y el que nosotros aceptamos— y compartir el nombre
    haría que rotar uno rote el otro sin que nadie lo pida.
    """
    return os.environ.get("CONTALIBRA_SERVICE_TOKEN", "")


class EnvioRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def registrar(self, appointment_id: str, estado: str, *,
                  venta_id: int | None = None, error: str = "") -> dict:
        """Crea o actualiza la fila del turno, sumando un intento."""
        with self.session_factory.begin() as session:
            row = session.get(EnvioAContalibraRow, appointment_id)
            if row is None:
                row = EnvioAContalibraRow(appointment_id=appointment_id, intentos=0)
                session.add(row)
            row.estado = estado
            row.venta_id = venta_id
            # Se recorta y no se deja crecer: un traceback entero de httpx en
            # una columna que se muestra en pantalla es ruido, y el detalle
            # completo ya está en el log.
            row.error = (error or "")[:500]
            row.intentos = (row.intentos or 0) + 1
            row.actualizado = datetime.now(timezone.utc)
            session.flush()
            return _to_dict(row)

    def get(self, appointment_id: str) -> dict | None:
        with self.session_factory() as session:
            row = session.get(EnvioAContalibraRow, appointment_id)
            return _to_dict(row) if row else None

    def listar(self, solo_pendientes: bool = False) -> list[dict]:
        with self.session_factory() as session:
            consulta = select(EnvioAContalibraRow)
            if solo_pendientes:
                consulta = consulta.where(
                    EnvioAContalibraRow.estado.in_((PENDIENTE, ERROR, SIN_DESTINO))
                )
            rows = session.scalars(
                consulta.order_by(EnvioAContalibraRow.actualizado.desc())
            ).all()
            return [_to_dict(row) for row in rows]


async def enviar_consulta(
    *, appointment_id: str, fecha: str, descripcion: str, importe: Decimal,
    medio_pago: str, paciente: dict, iva_rate: Decimal | None = None,
) -> dict:
    """Manda la consulta y devuelve lo que contestó Contalibra.

    Levanta `httpx.HTTPError` o `RuntimeError` si no se pudo — el que llama
    decide qué hacer con eso, porque acá no se sabe si completar el turno puede
    esperar.
    """
    url = destino()
    if not url:
        raise RuntimeError("CONTALIBRA_URL no está configurada")

    cuerpo = {
        "sistema": SISTEMA,
        # 🔴 El id del turno, que es lo que hace idempotente al reintento del
        # otro lado. No la fecha ni el nombre: dos consultas del mismo paciente
        # el mismo día son dos consultas.
        "referencia": appointment_id,
        "fecha": fecha,
        "descripcion": descripcion,
        "importe": float(importe),
        "medio_pago": medio_pago,
        "paciente": {
            "nombre": paciente.get("name") or "Consumidor Final",
            "cuit": paciente.get("cuit") or "",
            "condicion_iva": paciente.get("condicion_iva") or "",
        },
        # 🔴 **La alícuota viaja con la consulta.** En salud el caso normal es el
        # EXENTO, y esa configuración es de la prestación —vive acá, por servicio
        # (ADR-027)—, no del negocio que factura. Sin mandarla, Contalibra usa su
        # default y una prestación exenta se declara al 21%: la feature entera
        # quedaría configurable y sin efecto, en silencio. `None` deja que decida
        # el otro lado, que es lo correcto cuando acá no hay nada configurado.
        "iva_rate": float(iva_rate) if iva_rate is not None else None,
        "facturar": True,
    }
    async with httpx.AsyncClient(timeout=TIMEOUT_SEGUNDOS) as cliente:
        respuesta = await cliente.post(
            f"{url}/api/integraciones/consultas",
            json=cuerpo,
            headers={SERVICE_TOKEN_HEADER: _token()},
        )
    if respuesta.status_code >= 400:
        # El cuerpo del error entra al mensaje: Contalibra contesta cosas
        # accionables ("no tiene configurado el usuario para integraciones") y
        # perderlas dejaría al usuario con un número de estado y nada más.
        raise RuntimeError(f"{respuesta.status_code}: {respuesta.text[:300]}")
    return respuesta.json()
