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
    #: 🔴 **Con qué se cobró el saldo.** Es el único dato del cobro que no se
    #: puede recalcular desde el turno: la seña queda en `deposits` con su medio,
    #: pero el medio del saldo llega en el pedido de completar y no se guardaba
    #: en ningún lado.
    #:
    #: Sin esto el reintento tenía que asumir `"efectivo"`, y eso **reintroduce
    #: en el reintento el mismo defecto que este cambio arregla**: un saldo
    #: cobrado por transferencia entraba a la caja de Contalibra como efectivo.
    #: El reintento sigue recalculando *el precio* de hoy — lo que se guarda es
    #: cómo se cobró, que es un hecho del pasado y no cambia.
    medio_del_saldo: Mapped[str] = mapped_column(String(40), default="")


def _to_dict(row: EnvioAContalibraRow) -> dict:
    return {
        "appointment_id": row.appointment_id, "estado": row.estado,
        "venta_id": row.venta_id, "error": row.error,
        "intentos": row.intentos, "actualizado": row.actualizado,
        "medio_del_saldo": row.medio_del_saldo,
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
                  venta_id: int | None = None, error: str = "",
                  medio_del_saldo: str | None = None) -> dict:
        """Crea o actualiza la fila del turno, sumando un intento.

        `medio_del_saldo=None` **conserva el que ya estaba**, y no lo pisa con
        vacío: el reintento no lo sabe —lo recalcula todo desde el turno— y
        borrarlo ahí dejaría al siguiente reintento sin el dato que este campo
        existe para guardar.
        """
        with self.session_factory.begin() as session:
            row = session.get(EnvioAContalibraRow, appointment_id)
            if row is None:
                row = EnvioAContalibraRow(appointment_id=appointment_id, intentos=0)
                session.add(row)
            row.estado = estado
            row.venta_id = venta_id
            if medio_del_saldo is not None:
                row.medio_del_saldo = medio_del_saldo[:40]
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


def pagos_del_turno(importe, sena, sena_pagada: bool, medio_del_saldo: str | None):
    """Cómo se cobró la consulta, medio por medio.

    🔴 **La seña y el saldo son dos cobros distintos, y pueden ser dos medios
    distintos.** Hasta el 2026-08-24 se mandaba el precio entero con un solo
    medio —el del saldo—, así que con 400 de seña por MercadoPago y 600 en
    efectivo, en Contalibra entraban **1000 en efectivo**. La venta cerraba por
    el total correcto y **el reparto de la caja quedaba mal**: el cierre no
    cuadra contra el arqueo y la diferencia no tiene de dónde salir.

    El motor de facturación local que se borró (ADR-036) sí repartía —registraba
    la seña con su medio y el saldo con el suyo, como dos movimientos de caja— y
    eso se perdió al mudarse. Esto lo devuelve.

    Vive acá y no en un router porque **la usan los dos caminos**: completar el
    turno y reintentar el envío. Escrita en uno solo, el otro volvería a mandar
    un pago único y el defecto seguiría vivo por la mitad.

    Los montos **cierran contra el importe por construcción**: el saldo es
    `importe - seña`, no un número aparte. Contalibra igual lo verifica y rebota
    con 422 si no suman, que es la defensa del otro lado.

    Cuando la seña cubre todo el precio el saldo es cero y **no viaja**: un pago
    de 0 crearía un movimiento de caja vacío en la contabilidad de allá.
    """
    pagos = []
    cobrado = 0
    if sena_pagada and sena is not None:
        pagos.append({
            "medio": sena.medio_pago or "efectivo",
            "monto": sena.amount,
            "referencia": "Seña",
        })
        cobrado = sena.amount
    saldo = importe - cobrado
    if saldo > 0:
        pagos.append({"medio": medio_del_saldo or "efectivo", "monto": saldo})
    return pagos


async def enviar_consulta(
    *, appointment_id: str, fecha: str, descripcion: str, importe: Decimal,
    pagos: list[dict], paciente: dict, iva_rate: Decimal | None = None,
) -> dict:
    """Manda la consulta y devuelve lo que contestó Contalibra.

    Levanta `httpx.HTTPError` o `RuntimeError` si no se pudo — el que llama
    decide qué hacer con eso, porque acá no se sabe si completar el turno puede
    esperar.

    🔴 **`pagos` es una lista, y ése es el punto.** Hasta el 2026-08-24 esto
    mandaba un solo `medio_pago` por el importe entero, y para un turno señado
    eso es mentira: la seña se cobra al reservar y el saldo al atender, y pueden
    ser medios distintos. Con 400 de seña por MercadoPago y 600 en efectivo, del
    otro lado entraban **1000 en efectivo**. La venta cerraba por el total
    correcto —la plata bien contada— y **el reparto de la caja quedaba mal**: el
    cierre no cuadra contra el arqueo y la diferencia no tiene de dónde salir.
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
        # 🔴 La lista, no un medio suelto. Contalibra **exige que sumen el
        # importe**: una venta que se marca cobrada tiene que estar cobrada
        # entera, así que si esto no cierra el pedido rebota con 422 y la
        # consulta queda visible en `/facturacion-externa` en vez de entrar
        # descuadrada.
        "pagos": [
            {
                "medio": p["medio"],
                "monto": float(p["monto"]),
                "referencia": p.get("referencia", ""),
            }
            for p in pagos
        ],
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
